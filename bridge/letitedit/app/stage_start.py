"""Complete, provider-neutral first messages. Never shorten an attachment to fit a client.

build() starts one of today's six stages (log, story, rough, fine, finish, review) or, with the phase table
(letitedit.app.phases, on by default), one of its AI phases (plan_rough, fine_finish, review_export): a phase attaches
the union of its stages' skills, guide sections and inputs, and asks for that phase alone."""
import hashlib
import json
import os
import re
from pathlib import Path

from letitedit.core.paths import CODE_ROOT

BASE_SKILLS = ('letitedit', 'letitedit-craft', 'letitedit-modes', 'letitedit-firstcut')
STAGE_SKILLS = {
    'log': ('letitedit-log',),
    'story': ('letitedit-story',),
    'rough': ('letitedit-rough',),
    'fine': ('letitedit-fine', 'letitedit-captions', 'letitedit-sound'),
    'finish': ('letitedit-finish', 'letitedit-sound', 'letitedit-captions', 'letitedit-graphics'),
    'review': ('letitedit-gate', 'letitedit-review', 'letitedit-fine', 'letitedit-captions', 'letitedit-sound'),
}
GUIDES = {
    'log': (), 'story': (),
    'rough': ('edits', 'items', 'effects'),
    'fine': ('edits', 'items', 'effects'),
    'finish': ('edits', 'items', 'effects', 'code'),
    'review': ('edits', 'items', 'effects'),
}
MAX_BYTES = 512_000
END = '\n--- END COMPLETE STAGE START ---\n'

# ------------------------------------------------------------------ routes (T331 P6d; T319's rule 2)
# A route is a fact about this video known when a stage starts: its music choice, captions, the Look's measured files,
# a Short, lean hand-offs, ... (the names are tests/t319x/rule_ledger.py's ROUTES and the P6 groups' extra routes).
# routes() reads them from the typed New video request (letitedit.app.new_video_request, the record beside the video,
# else the same facts read from the request's text), the brief, the resolved Look and the files on disk, never from
# words in the request's own boilerplate.
#
# REFERENCES: the skills' references/ files and the routes they are attached on. A file is attached in full when one
# of its routes applies, its skill is attached (or the route is one of its `alone` routes) and the stage is one of its
# `stages` (None: every stage its skill is attached at). Two kinds:
#   - the files the skill rewrites (T331 P6a-c) moved rules into, from text every stage attached in full before: on
#     whenever a stage starts complete, so each stage gets back what it carried before the rewrite, on the routes the
#     rules apply to (its skill's "Read by route" line or pointer already says to read the file in full there);
#   - `switch`: files that were always read by a pointer only and were never attached (manuals of calls, defaults and
#     how-tos): only with the route switch on (new_video_route_skills), each at the stages that do that work
#     (`switch_stages`), since they add bytes a start never carried (tests/t331/p6d/REPORT.md, "Sizes").
# Not attached, on purpose:
#   - every references/sources.md (citations, not instructions);
#   - letitedit-craft references/checks.md (how to run each Check with the tools; craft's SKILL.md keeps every Check
#     line and when it runs; P6a's map said `always`, about 14 KB on every step of every stage);
#   - letitedit-craft references/examples.md ("Read on demand": worked examples and calibration, never targets);
#   - letitedit-craft references/levers.md (`revision`: a revision from the person's notes never starts here);
#   - the use:* files: steadying or a speed change, a real picture, a font search, a generated picture, an object layer.
#     Each is an editorial choice made mid-stage with no typed predicate; its pointer sits where the choice is made and
#     says to read it first, and a Look's recipe can forbid a device as well as ask for it (a word match isn't a route);
#   - letitedit-lighting references/learn.md (`learn`: Learn runs never start through this starter).
MEASURED_FILES = ('visual.json', 'lighting.json', 'grade.json', 'sound.json', 'sources.json', 'graphic-kit.json')
LATER = ('rough', 'fine', 'finish', 'review')
REFERENCES = {
    # moved rules (P6a-c): on whenever a stage starts complete
    'letitedit-firstcut/references/lean-handoffs.md': {'routes': ('lean_handoffs',)},
    'letitedit-firstcut/references/measured-look.md': {'routes': ('look:measured',)},
    # also for cut flashes on any Look (P6b's review), with or without letitedit-broll attached
    'letitedit-broll/references/measured-look.md': {'routes': ('look:measured', 'cut_flashes'),
                                                    'alone': ('cut_flashes',), 'stages': LATER},
    'letitedit-captions/references/look-captions.md': {'routes': ('captions:look_system', 'look:measured')},
    'letitedit-sound/references/music-choice.md': {'routes': ('music:library', 'music:auto')},
    # switch on, never in the review (T319 rule 2: "Review phase: ... no score writing"; a re-score there reads it by
    # its pointer); off, every stage that carried sound's section 2a before the rewrite still gets it
    'letitedit-sound/references/written-music.md': {'routes': ('music:write', 'music:made', 'music:auto'),
                                                    'switch_stages': ('story', 'rough', 'fine', 'finish')},
    'letitedit-sound/references/learned-sound.md': {'routes': ('sound:measured', 'look:measured')},
    'letitedit-sound/references/song-when-posting.md': {'routes': ('music:trending', 'song')},
    # T353's switch (work_in_passes, on by default): the pass shape and each stage's step budget, on every stage
    'letitedit-craft/references/passes.md': {'routes': ('passes',)},
    # pointer-only manuals: with the route switch on, at the one stage that does the work, in this order of priority;
    # they give way, last first, when a start would pass MANUAL_SHARE of the client's limit (never a file above)
    # her skeleton, hook approaches and the meta phrases check 3.2 lists: where the opening is planned and built
    'letitedit-shorts/references/method.md': {'routes': ('deliverable:short',), 'switch': True,
                                              'switch_stages': ('story', 'rough')},
    # captions are made and styled in the finish (letitedit-finish runs letitedit-captions there)
    'letitedit-captions/references/tool-recipes.md': {'routes': ('captions:on',), 'switch': True,
                                                      'switch_stages': ('finish',)},
    'letitedit-captions/references/styles.md': {'routes': ('captions:on',), 'switch': True,
                                                'switch_stages': ('finish',)},
    # the score op, music on the timeline and the mix
    'letitedit-sound/references/tool-recipes.md': {'routes': ('music:library', 'music:own', 'music:made', 'music:auto'),
                                                   'switch': True, 'switch_stages': ('finish',)},
    # reframing and exporting per platform
    'letitedit-shorts/references/platforms.md': {'routes': ('deliverable:short',), 'switch': True,
                                                 'switch_stages': ('finish',)},
    'letitedit-graphics/references/devices.md': {'routes': ('skill:letitedit-graphics',), 'switch': True,
                                                 'switch_stages': ('finish',)},
    # transitions in the fine cut (letitedit-fine section 3 points here)
    'letitedit-motion/references/camera-moves.md': {'routes': ('skill:letitedit-motion', 'skill:letitedit-fine'),
                                                    'alone': ('skill:letitedit-fine',), 'switch': True,
                                                    'switch_stages': ('fine',)},
    'letitedit-motion/references/numbers.md': {'routes': ('skill:letitedit-motion',), 'switch': True,
                                               'switch_stages': ('finish',)},
}
MANUAL_SHARE = 0.85
# T354: a sub-step's first message is the only one its session gets (a phase's next step brings its own manuals in a
# later message), so its stage's manuals stay while the whole start fits the client's limit
SUBSTEP_MANUAL_SHARE = 1.0
# Read by a pointer only (see above): each is named, with why, so a new reference can't be left out by accident.
NOT_ATTACHED = {
    'letitedit-craft/references/checks.md': ('how to run each Check with the tools (P6a\'s map said `always`): craft\'s '
                                             'SKILL.md keeps every Check line and says when; 14 KB on every step of a '
                                             'stage for a how-to never attached before'),
    'letitedit-craft/references/examples.md': 'read on demand: examples and calibration numbers, never targets',
    'letitedit-craft/references/levers.md': 'revision: the person\'s notes after a cut, never a stage start',
    'letitedit-finish/references/steady-and-speed.md': 'use:steady, use:speed: chosen mid-stage, pointer first',
    'letitedit-graphics/references/images.md': 'use:generated_picture: chosen mid-stage, pointer first',
    'letitedit-graphics/references/real-pictures.md': 'use:real_picture: chosen mid-stage, pointer first',
    'letitedit-graphics/references/fonts.md': 'use:fonts: chosen mid-stage, pointer first',
    'letitedit-layers/references/object-layer.md': 'use:object_layer: chosen mid-stage, pointer first',
    'letitedit-lighting/references/learn.md': 'learn: Learn runs never start here',
    # T364 (the owner's rule 2, the skills as checklists): every rule stays in its SKILL.md; each skill's manual holds the
    # reasons, worked examples, measured timings and tool details behind them, read by pointer (use:manual)
    'letitedit-craft/references/manual.md': 'use:manual: the evidence tags and which stage uses which rule',
    'letitedit-sound/references/manual.md': "use:manual: the evidence and the tools' details behind the checklist",
    'letitedit-graphics/references/manual.md': 'use:manual: reasons and evidence behind the checklist, pointer first',
    'letitedit-graphics/references/stock.md': 'use:stock: stock chosen mid-stage, pointer first',
    'letitedit-graphics/references/object-in-scene.md': 'use:object_layer: chosen mid-stage, pointer first',
    'letitedit-shorts/references/manual.md': "use:manual: the evidence and the tools' details behind the checklist",
    'letitedit-broll/references/manual.md': "use:manual: what follow_motion changes, pointer first",
}
MUSIC_ROUTE = {'library': 'music:library', 'own': 'music:own', 'made': 'music:made', 'ai': 'music:made',
               'written': 'music:made', 'backdrop': 'music:made', 'trending': 'music:trending', 'none': 'music:none',
               'auto': 'music:auto'}
LOOK_CAPTION_SYSTEM = re.compile(r'inverted-then-white|shot_dependent|caption roles?\b|kinetic (?:role|caption)|'
                                 r'protected face|picture-following letters|blend[^.\n]{0,20}(?:difference|exclusion)',
                                 re.I)
CUT_FLASHES = re.compile(r'cut_flashes|cut[- ]flash|inverted flash|flash(?:es)? on (?:every|each|the) cuts?', re.I)
GRAPHICS = re.compile(r'\bgraphics?\b|pop.?ups?|stickers?|lower thirds?|\blabels?\b|annotat|diagram|\btitles?\b', re.I)
BROLL = re.compile(r'\bb[- _]?roll\b|cut.?away', re.I)

# The route switch (on by default): settings.json `new_video_route_skills`, LETITEDIT_NEW_VIDEO_ROUTE_SKILLS (1 or 0)
# wins. On, the conditional skills come from routes (ROUTE_SKILLS) instead of regular expressions over the whole
# request, a phase attaches its route-scoped list (letitedit.app.phases ROUTE_SCOPED), the review attaches no mode
# playbook, and REFERENCES' `switch` manuals are attached at their stages. Off, skill_names is today's.
ROUTE_SETTING = 'new_video_route_skills'
ROUTE_ENV = 'LETITEDIT_NEW_VIDEO_ROUTE_SKILLS'
# switch on: (routes, stages, pattern over the person's words, the brief, the plan and the Look, never the boilerplate)
ROUTE_SKILLS = {
    'letitedit-shorts': (('deliverable:short',), None, None),
    'letitedit-learned-look': (('look:measured',), None, None),
    'letitedit-broll': (('broll:yes', 'look:measured', 'cut_flashes'), ('story',) + LATER, None),
    'letitedit-sound': (('driver:music', 'song'), ('story', 'rough'), None),
    'letitedit-graphics': (('graphics:yes',), LATER, None),
    'letitedit-layers': ((), LATER, r'\blayers?\b|behind|stack|picture.in.picture|blend mode'),
    'letitedit-motion': ((), LATER, r'\bmotion\b|code.scene|animated title'),
    'letitedit-lighting': (('look:lighting',), LATER, r'\blighting\b|relight'),
}
# switch on, from the fine cut on (the orchestrator's decision of 22 Nov, PT 20:20, after T342's two reviews: no word
# matching decides these three there): graphics, layers and motion at the finish and the review on every route;
# graphics at the fine cut on every route; layers and motion at the fine cut unless every shot the story plan records
# is real footage (`footage:real_only`, plan_footage). A plan not written yet, a plan with no visual decision, any
# made, drawn, generated, stock or unclear shot, a Custom mix slider above None, a made or stacked item on the
# timeline, a measured Look, a Look's own caption system or a Theme keeps them. Before the fine cut (the rough
# stage) ROUTE_SKILLS still decides, as before.
ROUTE_FROM_FINE = ('letitedit-graphics', 'letitedit-layers', 'letitedit-motion')
FROM_FINE = ('fine', 'finish', 'review')
# a recorded shot that is the footage itself: it names the footage and nothing made, drawn, stacked or moving
REAL_SHOT = re.compile(r'\b(?:the (?:real |own |actual )?footage|real footage|(?:his|her|their|my|our|the) (?:own )?'
                       r'(?:clips?|shots?|takes?|camera)|filmed|talking head|on camera|b-?roll from the (?:folder|footage)|'
                       r'a clip of the footage)\b', re.I)
MADE_SHOT = re.compile(r'scene|draw|drew|code|generat|stock|\b3d\b|\bmaps?\b|graphic|animat|illustrat|diagram|motion|'
                       r'\btext\b|title|label|overlay|picture|image|photo|\bstill\b|sticker|emoji|caption|\bwords?\b|'
                       r'cut.?out|split|inset|\bpip\b|composit|behind|\bover\b|\bai\b|\bmade\b|render|model|circl|'
                       r'arrow|highlight|zoom|freeze|blur|mask|\bkey|green|logo|watermark|count|timer|\bbar\b|'
                       r'button|card|lower third|annotat|\bring\b|\bbox\b|window|side.by.side|world|screen|'
                       r'recording|slow|speed|reverse|loop|\bfx\b|effect|transition|wipe|flash', re.I)


# T342's switch (on by default, and only with the route switch on): settings.json `new_video_first_message`,
# LETITEDIT_NEW_VIDEO_FIRST_MESSAGE (1 or 0) wins. On (tests/t342/REPORT.md):
#   - letitedit-graphics is attached in the plan-and-rough phase too (the story step chooses a code scene's world),
#     on every route (ALWAYS_GRAPHICS); from the fine cut on, the route switch's rule above decides the three;
#   - a phase whose first step is followed by another (the fine cut, then the finish) attaches the first step's set:
#     the route switch's own set for the fine stage, less captions unless the cut has captions already. The rest (the
#     finish's own skills, captions and their finish-only manuals, and layers and motion when the fine cut's shots are
#     all real footage) comes in the message that starts the next step, in the same conversation; the session runner
#     sends it, confirms its delivery and accepts the phase only once it has;
#   - the guide's tool index lists in full the tools the session's tool profile offers (the runner passes them) and
#     names the rest, which the tool server's own instructions name too.
FIRST_SETTING = 'new_video_first_message'
FIRST_ENV = 'LETITEDIT_NEW_VIDEO_FIRST_MESSAGE'
ALWAYS_GRAPHICS = ('story', 'rough', 'finish', 'review')
# the Custom mix's sliders that bring something made or moving (new_video_custom.FIELDS), typed or in its recipe
CUSTOM_LINE = re.compile(r'^(Motion graphics|Overlays|Emoji and stickers|3D effects):\s*([A-Za-z ]+?)\.?\s*(?:\(|$)',
                         re.I | re.M)
CUSTOM_KEYS = ('motion', 'overlays', 'emoji', 'three_d')
CUSTOM_LABELS = {'motion graphics': 'motion', 'overlays': 'overlays', 'emoji and stickers': 'emoji',
                 '3d effects': 'three_d'}


def _switch(env, setting):
    forced = os.environ.get(env, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(setting) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def routes_on():
    """Whether conditional skills follow the routes on this install (the switch above; on by default)."""
    return _switch(ROUTE_ENV, ROUTE_SETTING)


def first_message_on():
    """Whether T342's first message is on (its switch above, on by default; it acts only with routes_on())."""
    return routes_on() and _switch(FIRST_ENV, FIRST_SETTING)


def _decisions(plan):
    """The story plan's recorded visual decisions (dicts), whatever shape the rest of the file has; None when the plan
    is missing or malformed in a way that hides them."""
    if not isinstance(plan, dict):
        return None
    beats = plan.get('beats')
    beats = list(beats) if isinstance(beats, list) else []
    deliverables = plan.get('deliverables')
    for deliverable in (deliverables.values() if isinstance(deliverables, dict) else ()):
        more = deliverable.get('beats') if isinstance(deliverable, dict) else None
        beats += list(more) if isinstance(more, list) else []
    found = [beat.get('visual_decision') for beat in beats if isinstance(beat, dict)]
    found = [d for d in found if isinstance(d, dict)]
    if isinstance(plan.get('visual_decision'), dict):
        found.append(plan['visual_decision'])
    return found


def _real_shot(decision):
    """Whether a visual decision's shot is the footage itself: no scene candidate, a `device` that names the footage,
    and nothing made, drawn, generated, stock, stacked or moving (MADE_SHOT) in any of its fields but the spoken `line`
    (a reason that says "a scene drawn in code" keeps the skills). Anything unclear is not."""
    candidate = decision.get('scene_candidate')
    if candidate not in (None, '', False) and not (isinstance(candidate, str) and
                                                   re.match(r"(?i)\s*(?:none|no|null|false|n/a|-)\s*$", candidate)):
        return False
    device = decision.get('device')
    rest = json.dumps({key: value for key, value in decision.items() if key not in ('line', 'scene_candidate')},
                      ensure_ascii=False, default=str)
    return isinstance(device, str) and bool(REAL_SHOT.search(device)) and not MADE_SHOT.search(rest)


def plan_footage(plan):
    """True only when the story plan records at least one visual decision and every one is the real footage
    (_real_shot); False otherwise: no plan, a malformed one, no decision recorded, or any other shot."""
    decisions = _decisions(plan)
    return bool(decisions) and all(_real_shot(decision) for decision in decisions)


def _custom(look, recipe_text):
    """The Custom mix sliders above None that bring something made or moving ({'motion', 'overlays', 'emoji',
    'three_d'}): from the Look's typed settings (`custom.sliders`), else its recipe's lines ("Motion graphics: High.")."""
    settings = look.get('settings') if isinstance(look, dict) else None
    settings = settings if isinstance(settings, dict) else {}
    found = set()
    for holder in (settings, settings.get('values')):
        custom = holder.get('custom') if isinstance(holder, dict) else None
        sliders = custom.get('sliders') if isinstance(custom, dict) else None
        if isinstance(sliders, dict):
            found |= {key for key, value in sliders.items() if key in CUSTOM_KEYS and _number(value) > 0}
    for label, level in CUSTOM_LINE.findall(recipe_text or ''):
        if level.strip().lower() not in ('none', '0'):
            found.add(CUSTOM_LABELS[label.lower()])
    return found


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _timeline_kinds(script):
    """What the cut already holds: 'made' (a made, drawn, graphic, text or motion item on a video track), 'stacked'
    (more than one video track with items), 'captions'. A shape it can't read counts as 'made' (the skills stay)."""
    found = set()
    if not isinstance(script, dict):
        return found
    try:
        from letitedit.timeline import made
    except Exception:  # noqa: BLE001
        made = None
    try:
        tracks = [track for track in script.get('tracks') or [] if isinstance(track, dict)]
        video = [track for track in tracks if track.get('kind') == 'video' and
                 any(isinstance(item, dict) and 'gap' not in item for item in track.get('items') or [])]
        if len(video) > 1:
            found.add('stacked')
        for track in video:
            for item in track.get('items') or []:
                if not isinstance(item, dict) or 'gap' in item:
                    continue
                if {'graphic', 'color', 'text', 'motion', 'html', 'image', 'scene', 'code_scene'} & set(item) or \
                        (made is not None and made.is_made(item)) or 'clip' not in item:
                    found.add('made')
        if any(isinstance(cap, dict) and cap.get('cues') for cap in script.get('captions') or []):
            found.add('captions')
    except (TypeError, AttributeError):
        found.add('made')
    return found


def _typed(request, project):
    """(facts, source, the person's own words) from the typed record beside the video, else from the request text."""
    from letitedit.app import new_video_request as typed
    if project is not None:
        project = Path(project)
        for folder in (project.parent, project.with_suffix('.letitedit')):
            try:
                record = typed.read(folder)
            except (typed.RequestError, OSError):
                record = None
            if record:
                return typed.facts(record), 'typed record', '\n'.join((record.get('about') or '',
                                                                      record.get('custom') or ''))
    text = request or ''
    words = re.findall(r"^What it's about, and what must stay in or stay out:[ \t]*(.*(?:\n(?!\n).*)*)", text, re.M)
    words += re.findall(r'^What to make: what I describe here:[ \t]*(.*)$', text, re.M)
    return typed.facts_from_text(text), 'request text', '\n'.join(words) if words else text


def _beside(paths, names):
    """The measured files (names) found beside the Look's recipe.md (as letitedit.looks.look_library's card lists)."""
    found = []
    for path in paths:
        path = Path(path.get('path') if isinstance(path, dict) else path)
        if path.name.lower() == 'recipe.md':
            found += [name for name in names if path.with_name(name).is_file()]
    return list(dict.fromkeys(found))


def _value(brief, key):
    value = (brief or {}).get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return value.strip().lower() if isinstance(value, str) and value.strip() else value


def routes(stage, request='', brief=None, look=None, *, project=None, lean=False, recipe_text='', editorial='',
           timeline='', stop_after=None, first=False, plan=None):
    """The routes that apply to this start: {'routes': sorted names, 'facts': the typed facts, 'from': where they were
    read ('typed record' or 'request text'), 'measured': the Look's measured files, 'words': the person's own words}.
    stage is a stage name or an AI phase id; look the resolved Look ({id, settings, artifacts[, measured]}).
    first: T342's switch (first_message_on): the same routes, marked `first`. plan: the story plan (else read from
    the project's folder when there is one, with the route switch on) for `footage:real_only`."""
    brief = brief or {}
    look = look or {}
    facts, source, words = _typed(request, project)
    active = {'always'}
    if facts.get('turbo'):
        active.add('turbo')
    if re.search(r'^What to make:', request or '', re.M) or source == 'typed record':
        active.add('new_video')
    if lean:
        active.add('lean_handoffs')
    if stage not in STAGE_SKILLS:
        active.add('phases')
    if stop_after:
        active.add('stop_after')
    from letitedit.app import work_in_passes      # T353: the pass shape, attached with its switch on
    if work_in_passes.enabled():
        active.add(work_in_passes.ROUTE)
    if 'sessions: one per stage' in (request or '').splitlines():
        active.add('sessions_one_per_stage')
    if facts.get('no_footage'):
        active.add('no_footage')
    if facts.get('multicam'):
        active.add('multicam')
    # the Look: measured files beside its recipe (a learned Look, or a library Look with visual.json and the rest)
    measured = _beside(look.get('artifacts') or [], MEASURED_FILES)
    if isinstance(look.get('measured'), (list, tuple)):
        measured += [name for name in look['measured'] if name not in measured]
    elif look.get('measured'):
        measured.append('measured')
    identity = look.get('id')
    if measured:
        active.add('look:measured')
    elif identity in (None, '', 'none', 'neutral', 'freestyle'):
        active.add('look:auto' if facts.get('look_choice') == 'auto' and not brief.get('look') else 'look:none')
    elif identity == 'auto':
        active.add('look:auto')
    else:
        active.add('look:library')
    if 'sound.json' in measured:
        active.add('sound:measured')
    if {'lighting.json', 'grade.json'} & set(measured):
        active.add('look:lighting')
    look_text = recipe_text + '\n' + json.dumps(look.get('settings') or {}, ensure_ascii=False)
    if LOOK_CAPTION_SYSTEM.search(look_text):
        active.add('captions:look_system')
    theme = facts.get('theme') or _value(brief, 'theme')
    if theme not in (None, '', 'none', 'freestyle', 'auto'):
        active.add('theme')
    # music: the brief's choice (written once the AI has picked a route) wins over the request's auto
    music = (str(facts.get('music') or '').split() or ['auto'])[0]
    chosen = _value(brief, 'music')
    if music == 'auto' and isinstance(chosen, str) and chosen.split():
        music = chosen.split()[0]
    active.add(MUSIC_ROUTE.get(music, 'music:auto'))
    if music == 'written':
        active.add('music:write')
    if music != 'none':
        active.add('music:any')
    # a guide song's track (letitedit.sound.guide_song) in the timeline script, as YAML or JSON
    if facts.get('song') or _value(brief, 'song') or re.search(r'''(?:^|["':]\s*)song \(not in the export\)''',
                                                               timeline or '', re.I | re.M):
        active.add('song')
    if _value(brief, 'driver') in ('music', 'sound'):
        active.add('driver:music')
    # captions: on unless the person or the brief says none (auto: the captions skill decides, so its files come)
    captions = brief.get('captions')
    if isinstance(captions, bool):
        on = captions
    elif isinstance(captions, str) and captions.strip():
        on = captions.strip().lower() not in ('none', 'off', 'no', 'no captions', 'false')
    else:
        on = facts.get('captions', 'auto') not in ('none', 'off', 'no', 'no captions', 'false')
    active.add('captions:on' if on else 'captions:off')
    # a Short: the typed kind; a request without a `What to make:` line falls back to today's word match
    deliverables = json.dumps(brief.get('deliverables') or brief.get('deliverable') or '', ensure_ascii=False)
    typed_kind = 'new_video' in active and facts.get('kind') != 'custom'
    short = facts.get('short') if typed_kind else bool(re.search(r'\bshort(?:s)?\b', (request or '') + deliverables,
                                                                re.I))
    if re.search(r'short|vertical|9:16|reel|tiktok', deliverables, re.I):
        short = True
    if facts.get('kind') == 'custom' and re.search(r'\bshort(?:s)?\b|vertical|9:16', words, re.I):
        short = True
    active.add('deliverable:short' if short else 'deliverable:long')
    if typed_kind and facts.get('long'):
        active.add('deliverable:long')
    mode = _value(brief, 'mode')
    if isinstance(mode, str) and re.fullmatch(r'[a-z0-9-]+', mode):
        active.add('mode:' + mode)
    person = '\n'.join((words, json.dumps(brief, ensure_ascii=False), editorial))
    if CUT_FLASHES.search(person + '\n' + look_text):
        active.add('cut_flashes')
    settings = look.get('settings') or {}
    values = settings.get('values', settings) if isinstance(settings, dict) else {}
    amount = str(((values or {}).get('broll') or {}).get('amount') or '').lower() if isinstance(values, dict) else ''
    if 'visual.json' in measured or BROLL.search(person + '\n' + recipe_text) or amount not in ('', 'none', '0'):
        active.add('broll:yes')
    else:
        active.add('broll:no')
    answer = {'facts': facts, 'from': source, 'measured': measured, 'words': person}
    if GRAPHICS.search(person + '\n' + look_text) or 'graphic-kit.json' in measured or 'theme' in active:
        active.add('graphics:yes')
    # the fine cut's shots: real footage only (the route switch's rule for layers and motion at the fine cut; read
    # only with the route switch on, so a malformed plan never touches a default install's start)
    if routes_on():
        try:
            if plan is None and project is not None:
                path = Path(project).with_suffix('.letitedit') / 'story_plan.json'
                plan = _json(path) if path.is_file() else None
            from letitedit.app import phases as phase_table
            script = phase_table.read_script(project) if project is not None else None
            keeps = (_custom(look, recipe_text) or {'made', 'stacked'} & _timeline_kinds(script) or
                     {'look:measured', 'captions:look_system', 'theme'} & active)
            if plan_footage(plan) and not keeps:
                active.add('footage:real_only')
        except Exception:  # noqa: BLE001 - an unreadable plan or timeline means the skills stay
            pass
    if first:           # T342: the routes stay the route switch's
        answer['first'] = True
    answer['routes'] = sorted(active)
    return answer


def text_routes(brief=None, look_recipe=''):
    """The routes from a brief and the chosen Look's recipe text alone (the review panel, which has neither the request
    nor the Look's folder): the brief's music, song and captions; the Look measured when its recipe names a measured
    file or the Look is a learned one (`mine-`) whose recipe says it is measured."""
    brief = brief if isinstance(brief, dict) else {}
    recipe = look_recipe or ''
    measured = [name for name in MEASURED_FILES if name in recipe]
    identity = brief.get('look')
    if not measured and isinstance(identity, str) and identity.startswith('mine-') and re.search(r'\bmeasured\b',
                                                                                                   recipe, re.I):
        measured = ['measured']
    look = {'id': identity, 'settings': {}, 'artifacts': [], 'measured': measured}
    return set(routes('review', '', brief, look, recipe_text=recipe)['routes'])


def references(skills, active, stages, root=CODE_ROOT, switched=False, substep=None, scoped=False):
    """The references/ files (paths relative to skills/) attached for these skills, routes and stages, in a fixed order.
    switched: the route switch is on (routes_on), which adds the pointer-only manuals and their stage scopes.
    scoped: T363's switch (scoped_skills_on) for a sub-step's start (substep): the written-music manual only where the
    score is written (SCOPED_WRITTEN_MUSIC)."""
    active = set(active) | {'skill:' + name for name in skills}
    out = []
    for rel, rule in REFERENCES.items():
        if rule.get('switch') and not switched:
            continue
        if scoped and rel == WRITTEN_MUSIC and substep is not None and not _writes_score_here(substep, active):
            continue
        owner = rel.split('/', 1)[0]
        hits = [route for route in rule['routes'] if route in active]
        if not hits:
            continue
        if owner not in skills and not set(hits) & set(rule.get('alone', ())):
            continue
        scope = rule.get('switch_stages', rule.get('stages')) if switched else rule.get('stages')
        if scope is not None and not set(stages) & set(scope):
            continue
        if (Path(root) / 'skills' / rel).is_file():
            out.append(rel)
    return out


# ------------------------------------------------------------------ T363's cut 4: rule 2's scoping, by sub-step
# The switch: settings.json `substep_scoped_skills` (default true; LETITEDIT_SUBSTEP_SCOPED_SKILLS, 1 or 0, wins). It
# acts only on a sub-step's first message (letitedit.app.substeps: the session runner with sub-step sessions on), where
# the run is a first cut with nobody in the conversation and the person's later notes start a fresh chat. On:
#   - each skill's copy carries the `##` sections letitedit.app.skill_scope gives that sub-step; anywhere else the
#     section is left out of the copy, its heading kept, followed by one line that says why and where the whole text
#     is. A skill whose body isn't the one its entries were checked against (body_sha1) is attached in full, and so is
#     anything the data doesn't name, the text before the first `##`, and a named section whose heading isn't in the
#     skill once. Widening the scoping is adding entries there; test_session_side_cuts checks the data;
#   - skill_scope.ATTACH: the skills a sub-step's work needs that its route doesn't attach (letitedit-story at the
#     rough cut, letitedit-fine in the review);
#   - every skill's YAML frontmatter is left out of its copy (its name and description are the Skill tool's trigger
#     and nothing reads them from the attached text; the attachment's header names the skill);
#   - the written-music manual only at the finishing sub-step, where the score is written, or earlier when the music
#     drives the cut; never in the review ("no score writing"). letitedit-sound's section 2a still says to read it in
#     full before the first score.
# Off, every skill is attached in full, byte for byte as before.
SCOPED_SETTING = 'substep_scoped_skills'
SCOPED_ENV = 'LETITEDIT_SUBSTEP_SCOPED_SKILLS'
WRITTEN_MUSIC = 'letitedit-sound/references/written-music.md'
_REVIEW = ('review_rounds', 'final_look')
SCOPED_HEAD = ('Some attached skills leave out `##` sections this sub-step\'s work never does: each keeps its heading, '
               'followed by a line that says why it was left out and where the whole section is. Those skills are '
               'still attached (their frontmatter aside): do not load them again; read a left-out section only if '
               'this sub-step\'s work truly needs it.\n')


def scoped_skills_on():
    """Whether a sub-step's start leaves out the skill sections its work never does (T363's cut 4; on by default)."""
    return _switch(SCOPED_ENV, SCOPED_SETTING)


def _writes_score_here(substep, active):
    """The written-music manual's place with T363's switch on: the finishing sub-step, or an earlier one when the music
    drives the cut; never the review."""
    if substep in _REVIEW:
        return False
    return substep == 'finishing' or 'driver:music' in set(active)


def heading_name(heading):
    """A `##` heading's name: its `##`, its number ("4. ", "1b. ") and a closing parenthesis left out, in lower case."""
    text = re.sub(r'^#+\s*', '', str(heading).strip())
    text = re.sub(r'^\d+[a-z]?\.\s*', '', text)
    text = re.sub(r'\s*\([^()]*\)\s*$', '', text)
    return text.strip().rstrip('.').strip().lower()


def skill_parts(text):
    """[(heading or None, text)]: a SKILL.md cut at its `## ` lines; joined in order they are the text exactly."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, line in enumerate(lines) if line.startswith('## ')]
    cuts = [0] + heads + [len(lines)]
    parts = []
    for a, z in zip(cuts, cuts[1:]):
        if a == z:
            continue
        chunk = ''.join(lines[a:z])
        parts.append((lines[a][3:].strip() if lines[a].startswith('## ') else None, chunk))
    return parts


def frontmatter(text):
    """(frontmatter, rest): a SKILL.md's YAML frontmatter (from its first `---` line through the closing one and the
    line break after it), else ('', text)."""
    if not text.startswith('---'):
        return '', text
    match = re.match(r'---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)', text, re.S)
    return (match.group(0), text[match.end():]) if match else ('', text)


def body_sha1(text):
    """The hash skill_scope.SKILLS keeps per skill: of the SKILL.md body after its frontmatter, with LF line ends."""
    return hashlib.sha1(frontmatter(text)[1].replace('\r\n', '\n').encode('utf-8')).hexdigest()


def scope_of(skill, text):
    """{heading name: {'in': needed sub-steps, 'assessed': sub-steps checked, 'why': line or None}}: the entries of
    skill_scope that act on this text. None act when the text's body isn't the one they were checked against; an entry
    acts only when its heading is in the text once."""
    from letitedit.app import skill_scope
    row = skill_scope.SKILLS.get(skill)
    if not row or body_sha1(text) != row['body_sha1']:
        return {}
    counts = {}
    for heading, _ in skill_parts(frontmatter(text)[1]):
        if heading is not None:
            counts[heading_name(heading)] = counts.get(heading_name(heading), 0) + 1
    whys = {heading_name(name): line for name, line in (skill_scope.WHY.get(skill) or {}).items()}
    out = {}
    for heading, needed in row['sections'].items():
        key = heading_name(heading)
        if counts.get(key) == 1:
            out[key] = {'in': tuple(needed), 'assessed': tuple(row['assessed']), 'why': whys.get(key)}
    return out


def _uses(needed):
    from letitedit.app import substeps
    titles = [f"'{substeps.SUBSTEPS[name]['title']}'" for name in needed if name in substeps.SUBSTEPS]
    words = titles[0] if len(titles) == 1 else ', '.join(titles[:-1]) + ' and ' + titles[-1]
    return f'this run uses it in the {words} sub-step' + ('s' if len(titles) > 1 else '')


def scoped_skill(skill, text, substep, path=None, front=False):
    """(text, left out): a sub-step's copy of a skill with the sections skill_scope doesn't give that sub-step left out
    (each keeps its heading and gets one line saying why and where the whole is), and with front=True its frontmatter
    left out too. left out: [{'skill', 'section', 'bytes'}] (the frontmatter's section is 'frontmatter')."""
    left = []
    drop = {key: entry for key, entry in scope_of(skill, text).items()
            if substep in entry['assessed'] and substep not in entry['in']}
    if front:
        head, rest = frontmatter(text)
        if head:
            left.append({'skill': skill, 'section': 'frontmatter', 'bytes': len(head.encode('utf-8'))})
            text = rest
    if not drop:
        return text, left
    out = []
    where = f'skills/{skill}/SKILL.md' if path is None else str(path)
    for heading, chunk in skill_parts(text):
        key = heading_name(heading) if heading is not None else None
        if key in drop:
            first = chunk.splitlines(keepends=True)[0]
            first = first if first.endswith('\n') else first + '\n'
            why = drop[key]['why'] or _uses(drop[key]['in'])
            out.append(first + f'[Left out of this sub-step\'s copy by letitedit: {why}. If this sub-step\'s work '
                       f'truly needs it, read this section in {where}.]\n\n')
            left.append({'skill': skill, 'section': heading, 'bytes': len(chunk.encode('utf-8'))})
        else:
            out.append(chunk)
    return ''.join(out), left


def scoped_attach(substep):
    """The skills a sub-step's start adds with the switch on (skill_scope.ATTACH)."""
    from letitedit.app import skill_scope
    return tuple(skill_scope.ATTACH.get(substep, ()))


class IncompleteStart(ValueError):
    """Keep the current session or report the failure; do not launch a partial stage."""


def _unit(stage):
    """(stages, own skills, guide sections, phase entry or None) for a stage name or an AI phase id."""
    if stage in STAGE_SKILLS:
        return (stage,), STAGE_SKILLS[stage], GUIDES[stage], None
    from letitedit.app import phases, substeps
    if stage in substeps.SUBSTEPS:                  # T354: a sub-step of a phase, its own session
        entry = substeps.SUBSTEPS[stage]
        return entry['stages'], entry['skills'], entry['guides'], entry
    entry = phases.PHASES.get(stage)
    if entry is None or entry['who'] == 'code':
        raise IncompleteStart(f'Unknown New video stage: {stage}')
    return entry['stages'], entry['skills'], entry['guides'], entry


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _bytes(path):
    return Path(path).read_bytes().decode('utf-8')


def _identity(request, brief):
    match = re.search(r'^look:[ \t]*(.+)$', request, re.I | re.M)
    choice = match.group(1).strip() if match else None
    identity = re.search(r'\(([a-z0-9-]+)\)$', choice or '')
    selected = brief.get('look') or (identity.group(1) if identity else choice)
    return selected.lower() if isinstance(selected, str) and selected.lower() in ('auto', 'none', 'freestyle') else selected


def _look(request, brief, root, supplied):
    identity = _identity(request, brief)
    if supplied is not None and not isinstance(supplied, dict):
        raise IncompleteStart('Supply a resolved Look object, not a recipe excerpt.')
    if supplied is not None and not (identity not in (None, '', 'auto', 'none', 'freestyle') and
                                     supplied.get('id') in (None, '', 'auto', 'none', 'freestyle')):
        return supplied
    if not identity or identity in ('auto', 'freestyle', 'none'):
        return {'id': identity, 'settings': {}, 'artifacts': []}
    catalog = _json(root / 'looks' / 'manifest.json')
    entry = next((item for item in catalog['looks'] if item['id'] == identity), None)
    if entry is None:
        paths = re.findall(r'(?:[A-Za-z]:[\\/]|/)[^\r\n`"<>]*?recipe\.md', request)
        recipes = list(dict.fromkeys(path for path in paths if Path(path).is_file()))
        matching = [path for path in recipes if identity in Path(path).parts]
        if matching:
            recipes = matching
        if len(recipes) == 1:
            return {'id': identity, 'settings': {}, 'artifacts': recipes}
        raise IncompleteStart('Supply the resolved personal Look and its exact recipe/settings paths.')
    paths = [root / 'looks' / entry['recipe']]
    if entry.get('recipe_shared'):
        paths.append(root / 'looks' / entry['recipe_shared'])
    paths.extend(root / path for path in entry.get('read_also', []))
    settings = {}
    if entry.get('settings'):
        # the stored file also holds the neutral defaults the Look doesn't set: give only the Look's own (T332)
        from letitedit.looks import look_library
        settings = json.loads(json.dumps(look_library.library_own(identity, root / 'looks'), default=str))
    return {'id': identity, 'settings': settings, 'artifacts': [str(path) for path in paths]}


def skill_names(stage, request='', brief=None, look_text='', extra=(), route=None):
    """Router requirements known at launch; later editorial choices still load full skills.
    route: routes()'s answer; with the route switch on (routes_on) the conditional skills follow it instead of
    regular expressions over the whole request, and a phase attaches its route-scoped list."""
    stages, own, _, phase = _unit(stage)
    brief = brief or {}
    if route is not None:
        return _route_skill_names(stage, stages, own, phase, route, look_text, extra)
    names = list(BASE_SKILLS + tuple(own))
    context = request + '\n' + json.dumps(brief, ensure_ascii=False)
    if re.search(r'\bshort(?:s)?\b', context, re.I):
        names.append('letitedit-shorts')
    context += '\n' + look_text
    conditional = {
        'letitedit-broll': r'\bb[- _]?roll\b|cut.?away',
        'letitedit-layers': r'\blayers?\b|behind|stack|picture.in.picture|blend mode',
        'letitedit-motion': r'\bmotion\b|code.scene|animated title',
        'letitedit-lighting': r'\blighting\b|relight',
        'letitedit-learned-look': r'\bmeasured (?:files|look|lighting|sound|visual|devices)\b|mine-[a-z0-9]',
        'letitedit-graphics': r'\bgraphics?\b|pop.?ups?|stickers?',
        'letitedit-captions': r'\bcaptions?\b',
        'letitedit-sound': r'\bmusic\b|\bsound\b|\baudio\b',
    }
    if set(stages) <= {'log', 'story'}:
        early = {'letitedit-learned-look'}
        if 'story' in stages:
            early.add('letitedit-broll')
            if brief.get('driver') in ('music', 'sound'):
                early.add('letitedit-sound')
        conditional = {name: pattern for name, pattern in conditional.items() if name in early}
    names.extend(name for name, pattern in conditional.items() if re.search(pattern, context, re.I))
    names.extend(extra)
    if any(not isinstance(name, str) or not re.fullmatch(r'letitedit(?:-[a-z0-9]+)*', name) for name in names):
        raise IncompleteStart('Required skills must be full letitedit skill names, not sections or paths.')
    return list(dict.fromkeys(names))


def _checked(names):
    if any(not isinstance(name, str) or not re.fullmatch(r'letitedit(?:-[a-z0-9]+)*', name) for name in names):
        raise IncompleteStart('Required skills must be full letitedit skill names, not sections or paths.')
    return list(dict.fromkeys(names))


def _route_skill_names(stage, stages, own, phase, route, look_text, extra):
    """The switch-on skill list: the stage's own skills (a phase's route-scoped list), then each ROUTE_SKILLS entry
    whose route applies at one of these stages, or whose pattern is in the person's words, the brief, the plan or the
    Look (never in the request's boilerplate)."""
    active = set(route['routes'])
    if phase is not None:
        from letitedit.app import phases, substeps
        scoped = substeps.ROUTE_SCOPED[stage] if stage in substeps.SUBSTEPS else phases.ROUTE_SCOPED[stage]
        own = tuple(scoped['core']) + tuple(name for name, wanted in scoped['routed'].items() if active & set(wanted))
    names = list(BASE_SKILLS + tuple(own))
    context = route.get('words', '') + '\n' + look_text
    later = set(stages) & set(FROM_FINE)
    for name, (wanted, where, pattern) in ROUTE_SKILLS.items():
        if name in ROUTE_FROM_FINE and later:
            continue                                    # decided below, from the fine cut on
        if where is not None and not set(stages) & set(where):
            continue
        if active & set(wanted) or (pattern and re.search(pattern, context, re.I)):
            names.append(name)
    if later:
        names.append('letitedit-graphics')
        if later - {'fine'} or 'footage:real_only' not in active:
            names += ['letitedit-layers', 'letitedit-motion']
    if route.get('first') and set(stages) & set(ALWAYS_GRAPHICS):    # T342: graphics on every route there
        names.append('letitedit-graphics')
    names.extend(extra)
    return _checked(names)


def _timeline(project):
    from letitedit.timeline import edit_script
    from letitedit.app import letitedit_instances, live_edit
    source = project
    for row in letitedit_instances.list_instances():
        if row.get('project') and Path(row['project']).resolve() == project.resolve():
            source, _ = live_edit.snapshot(row['instance_id'])
            break
    script = edit_script.read(source)
    script['project'] = str(project)
    return edit_script.to_yaml(script)


def build(request, stage, project, *, ai='claude', handover=None, timeline=None, look=None,
          skills=(), evidence=(), input_record=None, lean=False, max_bytes=MAX_BYTES, root=CODE_ROOT,
          stop_after=None, end_turn_after=None, tools=None, by_step=False, step_from=None, sent=None):
    """Return request, attachment offsets/checksums and total checksum for a new provider session.

    timeline, when supplied, is the editor's complete authoritative live edit script (not a page).
    look is {id, settings, artifacts: [paths or {path, sha256}]}, as in a lean run.
    input_record is the person's staged Look-input JSON before it is kept beside the project.
    max_bytes is the receiving client's actual UTF-8 message limit; overflow is an error.
    stage may be an AI phase id (phases.AI_PHASES); stop_after names the sub-step a preview of that phase ends at.
    end_turn_after names a sub-step after which the AI ends its turn and the phase's next step comes in the next
    message (the session runner's model switch under Auto routing, T331 P10).
    tools: the letitedit tool names the session's tool server offers (its tool profile), when it has one.
    With T342's switch on (first_message_on): graphics, layers and motion by the video's own facts; with tools, the
    guide's tool index in full for those tools only; with by_step and end_turn_after inside a phase, the steps up to it
    get their own attachments here and the rest come in result['later'] (step_text), which the caller sends with the
    message that starts the next step (step_from: the step the phase's first message was for, when it is rebuilt
    later for that message; sent: the names of the attachments that first message held, so the next step gets
    everything else the phase needs now, from the files as they are then).
    """
    stages, _, guides, phase = _unit(stage)
    if phase is not None and lean:
        raise IncompleteStart('Lean stage hand-offs and phases are separate runs; start one or the other.')
    if ai not in ('claude', 'codex'):
        raise IncompleteStart('A stage starter needs the resolved Claude or Codex engine.')
    if not isinstance(request, str) or not request.strip():
        raise IncompleteStart('The original New video request is required.')
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise IncompleteStart('A positive client message byte limit is required.')
    root, project = Path(root), Path(project)
    work = project.with_suffix('.letitedit')
    brief = _json(work / 'brief.json') if (work / 'brief.json').exists() else {}
    resolved = _look(request, brief, root, look)
    if not isinstance(resolved, dict) or not {'id', 'settings', 'artifacts'} <= resolved.keys() or \
            not isinstance(resolved['settings'], dict) or not isinstance(resolved['artifacts'], list):
        raise IncompleteStart('Supply the complete resolved Look identity, settings and recipe paths.')
    identity = _identity(request, brief)
    if identity not in (None, '', 'auto', 'none', 'freestyle') and resolved['id'] != identity:
        raise IncompleteStart('The attached Look does not match the chosen Look.')
    attachments = []
    attached_paths = set()

    def attach(name, text, path=None):
        if not isinstance(text, str) or not text.strip():
            raise IncompleteStart(f'Missing full attachment: {name}')
        attachments.append((name, text, str(path) if path is not None else None))

    def file(name, path, sha256=None, into=None):
        text = _bytes(path)
        if sha256 and hashlib.sha256(text.encode('utf-8')).hexdigest() != sha256:
            raise IncompleteStart(f'Changed attachment: {path}')
        identity = str(Path(path).resolve())
        if identity in attached_paths:
            return
        attached_paths.add(identity)
        if into is not None:
            into.append((name, text, str(path)))
            return
        attach(name, text, path)

    if handover is not None:
        file('handover', handover)
    carried = ('brief.json', 'story_plan.json', 'selects.json', 'pickups.md', 'fine_pass.md', 'finish_pass.md',
               'inputs.json', 'review_memory.json')
    if phase is not None and phase.get('noun') == 'sub-step':     # T354: the files this sub-step's work reads
        carried = phase['carries']
    for name in carried:
        path = work / name
        if path.is_file():
            file(name, path)
    if 'story' in stages and (work / 'log.json').is_file():
        file('log.json', work / 'log.json')
    if input_record is not None:
        file('Look input record', input_record)
    if 'What the person gave this Look' in request and not (work / 'inputs.json').is_file() and input_record is None:
        raise IncompleteStart('Supply the staged Look input record before starting this stage.')
    attach('Look identity and settings', json.dumps(resolved, ensure_ascii=False, indent=2))
    recipe_text = ''
    for reference in resolved.get('artifacts', []):
        ref = {'path': reference} if isinstance(reference, str) else reference
        file('Look recipe/settings', ref['path'], ref.get('sha256'))
        recipe_text += _bytes(ref['path']) + '\n'
    if resolved.get('id') not in (None, '', 'none', 'auto', 'freestyle') and not recipe_text:
        raise IncompleteStart('The chosen Look needs its full recipe, not only its id.')
    for path in evidence:
        file('stage evidence', path)
    journal = work / 'journal.jsonl'
    lines = journal.read_text(encoding='utf-8-sig').splitlines() if journal.is_file() else []
    if phase is not None and phase.get('noun') == 'sub-step':
        # T354: an entry that only wrote a stage file attached above in full is left out of the tail (its text is
        # that file's); the ten before it come instead
        held = {name for name, _, _ in attachments}
        lines = [line for line in lines if _stage_file_entry(line) not in held]
        attach('journal tail (limit=10; entries that wrote a stage file attached above are left out)',
               '\n'.join(lines[-10:]) or 'No journal entries yet.')
    else:
        tail = lines[-10:]
        attach('journal tail (limit=10)', '\n'.join(tail) or 'No journal entries yet.')
    if timeline is None:
        if project.is_file():
            timeline = _timeline(project)
        elif stages[0] in ('log', 'story'):
            timeline = 'No project exists yet; no timeline edits have been made.'
        else:
            raise IncompleteStart('The editing stage needs the complete current timeline script.')
    if isinstance(timeline, dict):
        if any(key in timeline for key in ('page', 'next', 'truncated', 'items_total', 'partial')) or \
                any(track.get('partial') for track in timeline.get('tracks', [])):
            raise IncompleteStart('A paged or truncated timeline cannot start a stage.')
        timeline = json.dumps(timeline, ensure_ascii=False, indent=2)
    attach('current timeline script', timeline)
    editorial = '\n'.join(text for name, text, _ in attachments if name in ('story_plan.json', 'handover'))
    linked_skills = [Path(path).parent.name for path in sorted(attached_paths) if Path(path).name == 'SKILL.md']
    required = tuple(skills) + tuple(linked_skills)
    if resolved.get('measured'):
        required += ('letitedit-learned-look',)
    if phase is not None and phase.get('noun') == 'sub-step' and 'fine' in stages and routes_on():
        # T354: the fine sub-step is T342's fine step: captions only once the cut has captions (a revision)
        from letitedit.app import phases as phase_table
        if phase_table._has_captions(phase_table.read_script(project)):
            required += ('letitedit-captions',)
    switched = routes_on()
    first = switched and first_message_on()
    route = routes(stage, request, brief, resolved, project=project, lean=lean, recipe_text=recipe_text,
                   editorial=editorial, timeline=timeline, stop_after=stop_after, first=first)
    if 'turbo' in route['routes']:
        raise IncompleteStart('Turbo reads letitedit-turbo and nothing else; it starts with its own request.')
    names = skill_names(stage, request, brief, recipe_text + '\n' + editorial, required,
                        route=route if switched else None)
    substep = stage if phase is not None and phase.get('noun') == 'sub-step' else None
    scoped = substep is not None and scoped_skills_on()          # T363's cut 4
    if scoped:
        names = _checked(list(names) + list(scoped_attach(substep)))
    # T342: the steps up to end_turn_after get their own set; the rest waits for the message that starts the next step
    early = _early_steps(stage, stages, phase, project, end_turn_after, step_from) if first and by_step else None
    later, later_names, later_refs, later_guides = [], [], [], []
    if early:
        own = tuple(dict.fromkeys(name for one in early for name in STAGE_SKILLS[one]))
        kept = set(_route_skill_names(early[0], tuple(early), own, None, route, recipe_text + '\n' + editorial,
                                      required))
        # captions wait for the finish (letitedit-rough ROUGH-3, letitedit-finish runs letitedit-captions): before it
        # only a cut that already has captions (a revision) keeps them for the fine step
        from letitedit.app import phases as phase_table
        if 'finish' not in early and not phase_table._has_captions(phase_table.read_script(project)):
            kept.discard('letitedit-captions')
        later_names = [name for name in names if (name not in kept if sent is None else f'skill {name}' not in sent)]
    left_out = []
    for name in names:
        path = root / 'skills' / name / 'SKILL.md'
        if scoped:
            text, left = scoped_skill(name, _bytes(path), substep, front=True)
            if left:
                identity = str(path.resolve())
                if identity not in attached_paths:
                    attached_paths.add(identity)
                    (later if name in later_names else attachments).append(('skill ' + name, text, str(path)))
                    left_out += left
                continue
        file('skill ' + name, path, into=later if name in later_names else None)
    scope_refs = {'substep': substep, 'scoped': scoped}
    attached_references = references(names, route['routes'], stages, root, switched, **scope_refs)
    if early:
        now = set(references([name for name in names if name not in later_names], route['routes'], early, root,
                             switched, **scope_refs))
        later_refs = [rel for rel in attached_references
                      if (rel not in now if sent is None else f'reference {rel}' not in sent)]
    for rel in attached_references:
        file('reference ' + rel, root / 'skills' / rel, into=later if rel in later_refs else None)
    mode = brief.get('mode')
    if isinstance(mode, list):
        mode = mode[0] if mode else None
    review_only = set(stages) == {'review'}
    modes = _bytes(root / 'skills' / 'letitedit-modes' / 'SKILL.md')
    playbooks = dict(re.findall(r'\| ([a-z]+)(?:[^|]*)\| `references/([a-z-]+)\.md`', modes))
    if mode and not (switched and review_only):     # switch on: the review attaches no mode playbook (T319 rule 2)
        if not isinstance(mode, str) or not re.fullmatch(r'[a-z0-9-]+', mode):
            raise IncompleteStart('The lead mode must name its exact playbook.')
        file('lead mode reference', root / 'skills' / 'letitedit-modes' / 'references' /
             (playbooks.get(mode, mode) + '.md'))
    if 'multicam' in route['routes'] and not (switched and review_only):    # FIRST-1m: interview mode's multicam part
        file('mode reference (several angles of one talk)', root / 'skills' / 'letitedit-modes' / 'references' /
             (playbooks.get('interview', 'interview-podcast') + '.md'))
    guide = _bytes(root / 'GUIDE_V2.md')
    parts = re.split(r'(?m)(?=^## [a-z]+:)', guide)
    attach('guide index', scoped_index(parts[0], tools) if first and tools else parts[0])
    sections = {part.split(':', 1)[0][3:]: part for part in parts[1:]}
    guide_names = list(guides)
    if guide_names and any(name in names for name in ('letitedit-motion', 'letitedit-graphics')) and 'code' not in guide_names:
        guide_names.append('code')
    if early:
        now = [section for one in early for section in GUIDES[one]]
        if now and any(name in names and name not in later_names for name in ('letitedit-motion',
                                                                              'letitedit-graphics')):
            now.append('code')
        later_guides = [section for section in guide_names
                        if (section not in now if sent is None else f'guide {section}' not in sent)]
    for section in guide_names:
        if section in later_guides:
            later.append(('guide ' + section, sections[section], None))
        else:
            attach('guide ' + section, sections[section])
    if guides:
        from letitedit.timeline import op_specs
        attach('guide ops', op_specs.text())
    request_bytes = request.encode('utf-8')
    request_digest = hashlib.sha256(request_bytes).hexdigest()
    if phase is not None and phase.get('noun') == 'sub-step':
        start_line, continuation, step = _substep_lines(stage, phase, project, stop_after)
    elif phase is not None:
        start_line, continuation, step = _phase_lines(stage, phase, project, stop_after, end_turn_after)
    else:
        step = stage
        start_line = f'Start with the {stage} stage. Project: {project}\n'
        continuation = ('This run explicitly uses lean stage handoffs. Complete only this stage, then write the '
                        'structured FIRST-1s handover when the done-note reply requests it.\n' if lean else
                        'Without a hand_over request, continue to the next stage in this conversation as FIRST-1s '
                        'says; do not stop merely because this startup names one stage.\n')
    head = (request + f'\n\n--- original request | sha256:{request_digest} | bytes:{len(request_bytes)} ---\n'
            + start_line + continuation +
            'If you cannot continue on your own, start a plain line with "Blocked:" followed by the reason. '
            'If you found a workaround, say what you did and keep going.\n'
            'The skills and inputs below are attached in full; read every required skill IN FULL before working. '
            'Do not re-load attached skills, references, the Look or these guide sections. Read the rest in one '
            'step with '
            'the Skill tool: the lead mode reference if not yet chosen, and every skill the router or a fix needs. '
            'A missing or cut attachment is a startup failure, never permission to skip it. '
            'The original request, brief, permissions and handover stand; never repeat completed stages.\n')
    if left_out:
        head += SCOPED_HEAD
    following = None
    # the route switch left these out of the fine step's set (every recorded shot is the real footage); they come with
    # the next step, and the fine cut reads one itself the moment it needs it
    not_now = [name for name in later_names if name in ROUTE_FROM_FINE]
    if early and later:
        following = stages[stages.index(early[-1]) + 1]
        head += (f'The {following} step\'s own skills, references and guide sections ('
                 + ', '.join(name.split(' ', 1)[1] for name, _, _ in later
                             if name.split(' ', 1)[1] not in not_now)
                 + f') come attached in full in the message that starts the {following} step, in this conversation. '
                 f'End your turn when the {early[-1]} step is done, as said above, and never start the {following} '
                 'step\'s own work without them. Any skill the ' + early[-1] + ' step needs now, read IN FULL with '
                 'the Skill tool first; never wait for a later message for it.\n')
        if not_now:
            head += (' and '.join(not_now) + (' are' if len(not_now) > 1 else ' is') + ' not attached for the '
                     f'{early[-1]} step because every shot the story plan records is the real footage. If the '
                     f'{early[-1]} step adds a scene, a graphic, text, an overlay or anything that moves, read '
                     + ('that skill' if len(not_now) > 1 else 'it') + ' IN FULL with the Skill tool first.\n')

    def assemble(items, start=None):
        text = head if start is None else start
        manifest = [{'name': 'original request', 'path': None, 'start': 0, 'end': len(request),
                     'bytes': len(request_bytes), 'sha256': request_digest}]
        for name, body, path in items:
            payload = body.encode('utf-8')
            checksum = hashlib.sha256(payload).hexdigest()
            text += f'\n--- {name} | {path or "inline"} | sha256:{checksum} | bytes:{len(payload)} ---\n'
            start = len(text)
            text += body
            manifest.append({'name': name, 'path': path, 'start': start, 'end': len(text),
                             'bytes': len(payload), 'sha256': checksum})
            text += f'\n--- END {name} ---\n'
        return text + END, manifest

    text, manifest = assemble(attachments)
    payload = text.encode('utf-8')
    # a pointer-only manual (the switch's) gives way, last first, before a start passes MANUAL_SHARE of the limit:
    # its skill's pointer still names it; a required file above it is never dropped
    left = []
    manuals = [rel for rel in attached_references if REFERENCES[rel].get('switch') and rel not in later_refs]
    share = SUBSTEP_MANUAL_SHARE if phase is not None and phase.get('noun') == 'sub-step' else MANUAL_SHARE
    while manuals and len(payload) > max_bytes * share:
        rel = manuals.pop()
        left.insert(0, rel)
        attachments = [item for item in attachments if item[0] != 'reference ' + rel]
        attached_references = [name for name in attached_references if name != rel]
        text, manifest = assemble(attachments)
        payload = text.encode('utf-8')
    if len(payload) > max_bytes:
        raise IncompleteStart(f'Complete {stage} startup needs {len(payload)} bytes; client limit is {max_bytes}. '
                              'Nothing was cut. Increase the transport limit before starting this stage.')
    result = {'request': text, 'original_request': request, 'stage': stage, 'project': str(project), 'lean': lean,
              'folder': str(project.parent), 'ai': ai, 'skills': names, 'references': attached_references,
              'routes': route['routes'], 'routes_from': route['from'], 'route_skills': switched,
              'references_left': left, 'attachments': manifest,
              'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    if following:
        start = (f'--- the {following} step\'s attachments ---\n'
                 f'The {following} step starts now. Its own skills, references and guide sections are attached below '
                 'in full: read each IN FULL before working on this step, and do not load them again. Everything '
                 'attached in the first message still stands. If any of this step\'s work was already done, check '
                 'every change of it against these attachments and fix what they require before going on.\n')
        if not_now:
            start += (' and '.join(not_now) + (' were' if len(not_now) > 1 else ' was') + ' not with you during the '
                      f'{early[-1]} step: check every {early[-1]}-step change they govern (anything made, layered or '
                      'moving) against them too.\n')
        later_text, later_manifest = assemble(later, start)
        later_payload = later_text.encode('utf-8')
        if len(later_payload) > max_bytes:
            raise IncompleteStart(f'The {following} step\'s attachments need {len(later_payload)} bytes; client '
                                  f'limit is {max_bytes}. Nothing was cut.')
        result['later'] = {'step': following, 'request': later_text, 'skills': list(later_names),
                           'references': list(later_refs), 'guides': list(later_guides),
                           'attachments': later_manifest[1:], 'bytes': len(later_payload),
                           'sha256': hashlib.sha256(later_payload).hexdigest()}
    if first:
        result['first_message'] = True
    if left_out:
        result['left_out'] = left_out
    if phase is not None:
        result.update({'phase': stage, 'stages': list(stages), 'step': step, 'tools': phase['tools'],
                       'model_role': phase['model_role'], 'step_roles': dict(phase['step_roles']),
                       'end_turn_after': end_turn_after,
                       'outputs': list(phase['outputs'])})
        if phase.get('noun') == 'sub-step':
            result.update({'substep': stage, 'phase': phase['phase']})
    verify(result)
    if 'later' in result:
        verify(result['later'])
    return result


def _early_steps(stage, stages, phase, project, end_turn_after, step_from=None):
    """T342: the steps of a phase that its first message is for, when it ends its turn after end_turn_after and a
    step follows (the rest come with the message that starts the next step); else None."""
    if phase is None or not end_turn_after or end_turn_after not in stages[:-1]:
        return None
    from letitedit.app import phases
    now = step_from or phases.first_step(stage, project)
    if now not in stages or stages.index(now) > stages.index(end_turn_after):
        return None
    return list(stages[stages.index(now):stages.index(end_turn_after) + 1])


# T342: the phases whose first message is for their first step only, and that step (the session runner ends the turn
# after it and sends the rest with the message that starts the next step)
BY_STEP = {'fine_finish': 'fine'}


def step_split(phase, project):
    """The step after which the session runner ends the AI's turn so the next step's attachments come with the message
    that starts it (T342's switch on), or None: the phase starts at that step and has one after it."""
    step = BY_STEP.get(phase)
    if not step or not first_message_on():
        return None
    from letitedit.app import phases
    return step if phases.first_step(phase, project) == step else None


def step_text(bundle):
    """The attachments a phase's next step needs (T342), to send with the message that starts that step, or ''."""
    later = (bundle or {}).get('later')
    return later['request'] if later else ''


def scoped_index(index, tools):
    """The guide's index with its tool list cut to the tools a tool server offers (tools): those in full, the rest
    named, with how to reach them (as the tool server's own instructions say)."""
    offered = set(tools)
    kept, rest = [], []
    for line in index.split('\n'):
        match = re.match(r'- `(letitedit_[a-z0-9_]+)`:', line)
        if match and match.group(1) not in offered:
            rest.append(match.group(1)[len('letitedit_'):])
            continue
        kept.append(line)
    if not rest:
        return index
    from letitedit.core import paths
    note = ("- letitedit_guide is one of this session's tools: every guide section and every tool in full come from "
            "it (letitedit_guide('<topic>')). "
            f'The other {len(rest)} tools ({", ".join(rest)}) are not offered as tools in this session; only these '
            f'{len(rest)} are reached through the Python module letitedit_ai in {paths.BRIDGE_TEXT} (`import '
            "letitedit_ai; letitedit_ai.tool('<name>', **params)`), with the same arguments. Every tool listed above "
            'is called as a tool.')
    while kept and not kept[-1].strip():
        kept.pop()
    # the index's own opening says every tool is reached through letitedit_ai too; in a scoped session only the tools
    # left out are (the note), so that sentence keeps only what the pictures are
    text = SCOPED_OPENING.sub('Every picture', '\n'.join(kept))
    return text + '\n' + note + '\n\n'


SCOPED_OPENING = re.compile(r'Every tool is also a function of the\s+Python module `[^`]+`\s+\(`letitedit_ai\.tool\(name, '
                            r'\*\*params\)` reaches any of them\), and\s+every picture')


def _phase_lines(name, phase, project, stop_after=None, end_turn_after=None):
    """(start line, continuation, first sub-step) of a phase's first message."""
    from letitedit.app import phases
    step = phases.first_step(name, project)
    steps = ', '.join(phase['stages'])
    start = (f"Start with the {phase['title']} phase ({name}, phase {phase['number']} of {len(phases.AI_PHASES)}; "
             f"its steps: {steps}), at its {step} step. Project: {project}\n")
    lines = ['This run works in phases: each phase is its own conversation, started from the files on disk.']
    if name == phases.ORDER[-1]:
        lines.append('This is the last phase: the review rounds, their fixes, the final export and the closing '
                     'message (letitedit-firstcut section 4).')
        from letitedit.app import bookkeeping
        if bookkeeping.full():           # T345 C1
            lines.append('Markers follow their clips through every apply in this run, so the beat, why and cut '
                         'markers already on the timeline stay right; a clip a fix adds still needs its own `why:` '
                         'marker (letitedit-firstcut FIRST-4, FIRST-8).')
    else:
        following = phases.PHASES[phases.NEXT[name]]['title']
        from letitedit.app import bookkeeping
        books = ('Bookkeeping is done in code in this run: the `stage:<name>:done` marks when each step\'s outputs '
                 'check out, each main-track clip\'s `why:` marker from its select\'s `why` in selects.json, and the '
                 'hand-over to the next phase. Write none of them (letitedit-firstcut FIRST-1, FIRST-4).'
                 if bookkeeping.enabled() else
                 'Write each step\'s `stage:<name>:done` mark as usual; a mark alone does not end the phase.')
        if bookkeeping.full():           # T345 C1: the rest of the books
            books += (' Code also writes each beat\'s `beat:` marker and each loop\'s `loop:` markers from '
                      'story_plan.json, a `cut:` marker for each entry of selects.json\'s `cuts`, and the licence note '
                      'of each library song or sound on the timeline; markers follow their clips through every apply, '
                      'and the journal\'s reply to a stage file\'s note checks that file. Write none of them '
                      '(letitedit-rough ROUGH-4, letitedit-firstcut FIRST-4, letitedit-sound): the words stay yours, in '
                      'the plan\'s beat labels, the selects\' `why` and the `cuts` entries.')
        lines.append(f'Complete only this phase, then end your turn; the {following} phase starts in a fresh '
                     'conversation. The phase is done when its outputs check out in code: '
                     + '; '.join(phase['outputs']) + '. ' + books)
    if stop_after and stop_after in phase['stages']:
        lines.append(f'This run stops after the {stop_after} step (a preview): no step after it, no review, '
                     'no export.')
    elif end_turn_after and end_turn_after in phase['stages'] and end_turn_after != phase['stages'][-1]:
        lines.append(f'End your turn as soon as the {end_turn_after} step is done and saved: the rest of this phase '
                     'comes in the next message, in this same conversation.')
    return start, '\n'.join(lines) + '\n', step


STAGE_FILE_ENTRY = re.compile(r'(brief|log|selects|story_plan|pickups|fine_pass|finish_pass):\s')
STAGE_FILE_EXT = {'pickups': '.md', 'fine_pass': '.md', 'finish_pass': '.md'}


def _stage_file_entry(line):
    """The stage file a journal line wrote (`selects: {...}` wrote selects.json), or None."""
    try:
        text = str(json.loads(line).get('text') or '')
    except (ValueError, AttributeError):
        return None
    match = STAGE_FILE_ENTRY.match(text)
    return match.group(1) + STAGE_FILE_EXT.get(match.group(1), '.json') if match else None


def _substep_lines(name, spec, project, stop_after=None):
    """(start line, continuation, first stage) of a sub-step's first message (T354: a fresh session per sub-step)."""
    from letitedit.app import bookkeeping, phases, substeps
    step = substeps.first_step(name, project)
    parent = phases.PHASES[spec['phase']]
    start = (f"Start with the {spec['title']} sub-step ({name}, sub-step {spec['number']} of {len(substeps.ORDER)}, "
             f"in the {parent['title']} phase; its steps: {', '.join(spec['stages'])}), at its {step} step. "
             f'Project: {project}\n')
    rounds = None
    if name == 'review_rounds' and substeps.round_sessions_on():      # T363's cut 3: a session per review round
        memory = Path(project).with_suffix('.letitedit') / 'review_memory.json'
        try:
            rounds = len(_json(memory).get('rounds') or []) if memory.is_file() else 0
        except (OSError, ValueError, AttributeError):
            rounds = 0
    lines = ['This run works in sub-steps: each sub-step is its own conversation, started from the files on disk and, '
             'after the first, from a hand-off letitedit made from them and checked (attached as `handover`). The '
             'hand-off names every requirement of the brief, the overlay boxes, every review finding still open with '
             'its evidence, the device ledger and why each kept clip is in the cut: they stand for the whole edit.',
             f"This sub-step's work: {substeps.work(name, rounds=rounds)}."]
    following = substeps.NEXT.get(name)
    if following is None:
        lines.append('This is the last sub-step: the last review, its fixes, the final export and the closing message '
                     '(letitedit-firstcut section 4).')
        if bookkeeping.full():           # T345 C1
            lines.append('Markers follow their clips through every apply in this run, so the beat, why and cut '
                         'markers already on the timeline stay right; a clip a fix adds still needs its own `why:` '
                         'marker (letitedit-firstcut FIRST-4, FIRST-8).')
    else:
        books = ('Bookkeeping is done in code in this run: the `stage:<name>:done` marks when each step\'s outputs '
                 'check out, each main-track clip\'s `why:` marker from its select\'s `why` in selects.json, and the '
                 'hand-off to the next sub-step. Write none of them (letitedit-firstcut FIRST-1, FIRST-4); a clip no '
                 'select plays still needs its `why:` marker from you.'
                 if bookkeeping.enabled() else
                 'Write each step\'s `stage:<name>:done` mark and each main-track clip\'s `why:` marker as usual; a '
                 'mark alone does not end the sub-step.')
        if bookkeeping.full():           # T345 C1: the rest of the books
            books += (' Code also writes each beat\'s `beat:` marker and each loop\'s `loop:` markers from '
                      'story_plan.json, a `cut:` marker for each entry of selects.json\'s `cuts`, and the licence note '
                      'of each library song or sound on the timeline; markers follow their clips through every apply. '
                      'Write none of them (letitedit-rough ROUGH-4, letitedit-firstcut FIRST-4, letitedit-sound): the '
                      'words stay yours, in the plan\'s beat labels, the selects\' `why` and the `cuts` entries.')
        lines.append(f"Complete only this sub-step, then end your turn; the {substeps.SUBSTEPS[following]['title']} "
                     'sub-step starts in a fresh conversation with its own skills: never start its work here. This '
                     'sub-step is done when its outputs check out in code: ' + '; '.join(spec['outputs']) + '. '
                     + books)
        lines.append('The next sub-step knows only the files and the hand-off: once the cut has one, keep the device '
                     'ledger in a `devices:` note (letitedit-craft L1), and leave every review finding still open in '
                     "the review's own record. letitedit checks the hand-off in code before the next sub-step starts "
                     'and asks again for anything missing.')
    if stop_after and stop_after in spec['stages']:
        lines.append(f'This run stops after the {stop_after} step (a preview): no step after it, no review, '
                     'no export.')
    return start, '\n'.join(lines) + '\n', step


def verify(bundle, delivered=None):
    """Validate the exact text to be sent, including every attachment and the closing sentinel."""
    text = bundle['request'] if delivered is None else delivered
    payload = text.encode('utf-8')
    if not text.endswith(END) or len(payload) != bundle['bytes'] or \
            hashlib.sha256(payload).hexdigest() != bundle['sha256']:
        raise IncompleteStart('The stage startup was cut or changed; do not start the AI.')
    for item in bundle['attachments']:
        payload = text[item['start']:item['end']].encode('utf-8')
        if len(payload) != item['bytes'] or hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise IncompleteStart(f"The attachment {item['name']} was cut or changed; do not start the AI.")
    return True
