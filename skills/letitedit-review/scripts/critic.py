"""The critic: a separate run of an AI on the person's PC. It tries the AI that isn't editing, then the same AI as a fresh
session (ai_clis.critic_order). One that is missing, signed out, over its limit or gives no answer moves on, with no
retries; with nobody left, review.json says so in plain words ('error', 'error_kind').

python critic.py <export.mp4> --kind short|long --brief brief.json --out <folder> [--engine codex|claude]
                 [--bundle review_bundle.json] [--story-plan story_plan.json] [--project edit.mlt]

Shows it the WHOLE video: contact pages covering every part in time order (one frame every 1-4 s, labelled with its
time), a page of larger frames at key moments, the complete transcript of the render, the brief, the story plan's
logline / purpose and sections when there is a plan, and the gate's numbers; never the editor's reasoning. The plan:
--story-plan, else story_plan.json next to the project or the brief or in the bundle / out folder, else the newest
story-plan note in the project's journal. With --bundle it uses the pages of a review bundle (letitedit_review_bundle);
without, it makes its own. Every problem needs evidence and a severity; finding none is a valid answer. Writes
review.json (with 'story_plan': where the plan came from, or null; 'engine', 'model', 'effort', 'same_vendor': who
reviewed; 'attempts': tries that failed before it). --engine only says which to try first;
LETITEDIT_CRITIC_ENGINE (codex or claude) does the same when --engine is not given, for test runs.

With background runs turned off (Connect Your AI), no program is started from here: the review runs as a visible second
conversation in the letitedit window showing this video, which saves review.json itself; with no such window review.json says
so ('error_kind': 'background_off').

LETITEDIT_CRITIC_MODEL and LETITEDIT_CRITIC_EFFORT force a model and effort, whichever AI runs. Otherwise a critic uses the
model and effort the person saved in the chat's settings for the AI that runs it (the other AI too); under Auto (their
model is "auto") the planning role's (ai_list.json routing); else the app's default for it (Claude Opus at medium,
Codex GPT-6.1-Sol at medium). LETITEDIT_CRITIC_DEPTH=deep (for comparing review
designs) gives the critic frames twice as often and larger, the details page, the level graph, the timing pictures and
the whole transcript. LETITEDIT_CRITIC_DEPTH=panel runs a review panel instead (panel.py: a story critic on the
person's model, cheaper area reviewers in parallel, a merger). Each Claude run's token use is recorded in review.json
('usage'); review_bundle counts it in the run's cost. A dense video's reviewer also gets frame-by-frame strips of its motion, full-size frames
of its words on screen and the timing sheet (review_bundle's 'motion').
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(os.environ.get('LETITEDIT_ROOT', Path(__file__).resolve().parents[3]))
SOURCE_BRIDGE = Path(__file__).resolve().parents[3] / 'bridge'
sys.path.insert(0, str(SOURCE_BRIDGE if (SOURCE_BRIDGE / 'ai_clis.py').exists() else ROOT / 'bridge'))
import ai_clis  # noqa: E402 - from the bridge folder above
APP = ROOT / 'app'
FFMPEG, WHISPER = APP / 'ffmpeg.exe', APP / 'whisper-cli.exe'
MODEL = next(iter(sorted((ROOT / 'models').glob('ggml-*.bin'), key=lambda p: p.stat().st_size)), None)
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

ASK_TIMEOUT = 1800    # one AI's try; review_bundle and letitedit_critic allow for two
PANEL_POLL_S = 2      # how often to look for the answer of a review running in the panel
TRANSCRIPT_MAX = 60000
PLAN_MAX = 6000
MOTION_SHEET_MAX = 12000   # the timing sheet of a dense video (about 150 events)
# the kind of video (letitedit-modes): each mode file's gate section ends with the questions the critic should answer
MODES = Path(__file__).resolve().parents[2] / 'letitedit-modes' / 'references'
MODE_FILES = {'story': 'story-vlog.md', 'tutorial': 'tutorial-explainer.md', 'interview': 'interview-podcast.md',
              'documentary': 'documentary.md', 'product': 'product-commercial.md', 'travel': 'travel-event.md',
              'montage': 'montage-transformation.md', 'creative': 'creative-stylised.md'}
GENRE_MODE = {'diy': 'story', 'education': 'tutorial', 'business': 'product', 'travel': 'travel', 'day': 'story',
              'doc': 'documentary', 'before_after': 'montage'}


def _run(args, **kwargs):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=NO_WINDOW, **kwargs)


def _transcript(video):
    if not (WHISPER.exists() and MODEL):
        return ''
    with tempfile.TemporaryDirectory() as tmp:
        wav, base = Path(tmp) / 'audio.wav', Path(tmp) / 'audio'
        _run([FFMPEG, '-v', 'error', '-y', '-i', video, '-ar', '16000', '-ac', '1', wav])
        _run([WHISPER, '-m', MODEL, '-f', wav, '-osrt', '-of', base, '-np'])
        srt = base.with_suffix('.srt')
        return srt.read_text(encoding='utf-8', errors='replace') if srt.exists() else ''


def _clock(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:04.1f}'


def unheard_note(words, hearing):
    """What a reviewer is told the review couldn't hear: '' when it heard the talk, or when nothing is known.
    hearing: the bundle's {'heard': 'all' | 'part' | 'none', 'unheard': [[start, end], ...], 'ran': whether the speech
    model ran, 'talk': 'yes' | 'no' | 'unknown' (the edit's own words)}, or None."""
    heard = (hearing or {}).get('heard')
    gaps = [g for g in (hearing or {}).get('unheard') or [] if isinstance(g, (list, tuple)) and len(g) == 2]
    if not words.strip() or heard not in ('part', 'none') or not gaps:
        return ''
    where = ', '.join(f'{_clock(a)}-{_clock(b)}' for a, b in gaps[:8]) + (' and more' if len(gaps) > 8 else '')
    return (f"The speech model heard nothing at {where}, where the edit's own words have talk (music or noise may cover "
            "it there, or the model missed it). A line or claim that falls there is unconfirmed, not missing: never call "
            "it missing or cut for that. If the pictures or captions there suggest the words are buried, say so as a "
            "sound problem at that time."
            + (" It heard no words in the talk at all: say that the speech was not checked." if heard == 'none' else ''))


def transcript_text(words, hearing=None):
    """The critic's lines on the render's transcript: the words, and what the review couldn't hear (unheard_note)."""
    if words.strip():
        note = unheard_note(words, hearing)
        return ("The complete transcript of the render, with times, from a small speech model that mishears names and "
                "similar sounds. Where it reads oddly, or differs from the captions in the pictures, assume the model "
                f"misheard: that is at most a minor 'confirm by ear', never a problem with the edit:\n{words}\n"
                + (f"{note}\n" if note else ''))
    # only what was measured: whether the speech model ran ('ran') and whether the edit's own words have talk ('talk':
    # yes, no, or unknown when not all of them are known); an older bundle has neither
    h = hearing or {}
    heard, ran, talk = h.get('heard'), h.get('ran'), h.get('talk')
    if ran is False:
        why = ": the review's speech model didn't run" + {'yes': ", and the edit's own words have talk",
                                                           'no': ", and the edit's own words have no talk"}.get(talk, '')
    elif ran:
        why = ": the review's speech model heard no speech in it" + (
            ", though the edit's own words have talk" if talk == 'yes' and heard in ('none', 'part') else '')
    else:
        why = " (the review's speech model gave none: it may not be on this PC, or there was no speech)"
    end = (', and say that the speech was not checked.' if talk == 'yes' and heard in ('none', 'part') else
           '.' if talk in ('yes', 'no') else '; if the pictures show someone talking, say that the speech was not checked.')
    return (f"There is no transcript of the render{why}. That is not evidence that anything was left unsaid: never "
            "call a line or a claim missing for it, and judge what is said only from captions you can see" + end + '\n')


def compact_srt(text):
    """An SRT as one '[m:ss] text' line per cue: every word and its start time in about half the characters (cue
    numbers and end times dropped). Text that isn't SRT comes back as it was."""
    out = []
    for m in re.finditer(r'(\d+):(\d\d):(\d\d)[,.]\d{3} --> [^\n]*\n(.*?)(?:\n\s*\n|\Z)', text, re.S):
        h, mi, s = (int(x) for x in m.groups()[:3])
        out.append(f'[{h * 60 + mi}:{s:02d}] ' + ' '.join(m.group(4).split()))
    return '\n'.join(out) if out else text


def brief_modes(brief):
    """The brief's modes in order (the first leads); the old genre field maps to one."""
    modes = brief.get('mode') or GENRE_MODE.get(str(brief.get('genre') or '').lower())
    if isinstance(modes, str):
        modes = re.split(r'[,+/]\s*|\s+and\s+|\s+', modes.strip())
    return [m.strip().lower() for m in modes or [] if m and m.strip().lower() in MODE_FILES]


def mode_questions(modes):
    """[(mode, its critic questions)] from letitedit-modes/references/<mode>.md, section 8."""
    out = []
    for m in modes:
        f = MODES / MODE_FILES[m]
        if not f.is_file():
            continue
        text = f.read_text(encoding='utf-8', errors='replace')
        section = text.split('## 8.', 1)[-1].split('## 9.', 1)[0] if '## 8.' in text else ''
        found = re.search(r'Critic questions:\s*(.+\?)', ' '.join(section.split()))
        if found:
            out.append((m, found.group(1)))
    return out


def find_story_plan(explicit=None, project=None, brief=None, bundle=None, out=None):
    """(plan dict, where it came from) or (None, None): --story-plan, else story_plan.json next to the project, the
    brief, the bundle or in out, else the newest journal note of the project that is a story plan."""
    files = [Path(explicit)] if explicit else []
    if project:
        files += [Path(project).parent / 'story_plan.json', Path(project).with_suffix('') / 'story_plan.json']
    files += [Path(f).parent / 'story_plan.json' for f in (brief, bundle) if f]
    if out:
        files.append(Path(out) / 'story_plan.json')
    for f in files:
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding='utf-8-sig')), str(f)
            except ValueError:
                continue
    import project_journal  # noqa: E402 - the project's own folder, <stem>.letitedit (an old <stem>.shotcut moves there)
    journal = project_journal.folder(project) / 'journal.jsonl' if project else None
    if journal and journal.is_file():
        for line in reversed(journal.read_text(encoding='utf-8-sig', errors='replace').splitlines()):
            try:
                text = json.loads(line).get('text') or ''
            except (ValueError, AttributeError):
                continue
            body = re.sub(r'^\s*story[ _-]?plan\s*:', '', text, flags=re.I)
            if body.strip().startswith('{'):
                try:
                    data = json.loads(body)
                except ValueError:
                    continue
                if isinstance(data, dict) and any(k in data for k in ('logline', 'purpose', 'sections', 'beats')):
                    return data, f'{journal} (journal note)'
    return None, None


def _sections(plan, kind):
    """The plan's sections (or beats) for this kind of export, in order."""
    per = plan.get('deliverables')
    if isinstance(per, dict):
        mine = per.get(kind)
        if isinstance(mine, dict) and (mine.get('sections') or mine.get('beats')):
            return mine.get('sections') or mine.get('beats')
    if plan.get('sections') or plan.get('beats'):
        return plan.get('sections') or plan.get('beats')
    if isinstance(per, dict):
        found = [v.get('sections') or v.get('beats') for v in per.values() if isinstance(v, dict)
                 and (v.get('sections') or v.get('beats'))]
        if len(found) == 1:
            return found[0]
    return []


def plan_summary(plan, kind=None, limit=PLAN_MAX):
    """The story plan in a few lines for the critic: logline / purpose (and stakes, the open question, the feel and
    the ending when the plan has them), then its sections in order with their purpose, feel or gear, driver and
    connector."""
    lines = []
    for key, label in (('logline', 'Logline'), ('purpose', 'Purpose'), ('stakes', 'Stakes'),
                       ('open_question', 'Open question'), ('feel', 'Feel'), ('ending', 'Planned ending')):
        value = plan.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f'{label}: {value.strip()}')
    deliverable = (plan.get('deliverables') or {}).get(kind) if kind else None
    if isinstance(deliverable, dict):
        if deliverable.get('selected_story_s'):
            lines.append(f"Selected story length: {deliverable['selected_story_s']} s; "
                         f"why: {deliverable.get('length_reason') or 'not recorded'}")
        if deliverable.get('payoff_line'):
            lines.append(f"Exact payoff line: {deliverable['payoff_line']}")
        payoff = deliverable.get('payoff')
        if isinstance(payoff, dict) and payoff.get('description'):
            lines.append(f"Picture/sound payoff ({payoff.get('kind')}): {payoff['description']}; "
                         'judge the closing action and release in the export, not a spoken line')
    sections = _sections(plan, kind)
    if sections:
        lines.append('Sections, in order:')
    for i, s in enumerate(sections, 1):
        if not isinstance(s, dict):
            lines.append(f'{i}. {s}')
            continue
        name = s.get('label') or s.get('name') or s.get('title') or s.get('id') or f'section {i}'
        bits = [f'{i}. {name}']
        for key in ('purpose', 'feel', 'gear', 'driver', 'connector', 'target_s'):
            if s.get(key) not in (None, '', [], {}):
                bits.append(f'{key}: {s[key]}')
        lines.append('; '.join(str(b) for b in bits))
    text = '\n'.join(lines)
    return text if len(text) <= limit else text[:limit] + '\n[... plan shortened]'


def deep_material(video, out, bundle):
    """The deeper first look (LETITEDIT_CRITIC_DEPTH=deep, for comparing review designs): frames twice as often and
    half as large again, the details page, the level graph and the timing pictures, and the whole transcript."""
    import review_bundle
    gate = review_bundle._gate()
    info = gate.probe(Path(video))
    every = max(0.5, review_bundle.sample_every(info['duration']) / 2)
    portrait = (info['height'] or 0) > (info['width'] or 0)
    frames = review_bundle.sample_frames(gate.FFMPEG, video, every, 240 if portrait else 384, Path(out) / 'deep-frames')
    folder = Path(out) / 'deep-pages'
    folder.mkdir(parents=True, exist_ok=True)
    pages = [p['file'] for p in review_bundle.pages(frames, folder, portrait)]
    b = json.loads(Path(bundle).read_text(encoding='utf-8-sig')) if bundle and Path(bundle).exists() else {}
    files = b.get('files') or {}
    extra = [files.get('details'), files.get('audio'), *(b.get('timing_images') or files.get('timing_images') or [])]
    pages += [str(x) for x in extra if x and Path(x).exists()]
    srt = files.get('transcript')
    text = Path(srt).read_text(encoding='utf-8', errors='replace') if srt and Path(srt).exists() else _transcript(video)
    return pages, text, every


def material(video, kind, out, bundle):
    """(page image paths, transcript text, every_s) for the whole video."""
    if os.environ.get('LETITEDIT_CRITIC_DEPTH') == 'deep':
        return deep_material(video, out, bundle)
    if bundle and Path(bundle).exists():
        b = json.loads(Path(bundle).read_text(encoding='utf-8-sig'))
        files = b.get('files') or b
        pages = [p['file'] for p in (files.get('pages') or b.get('pages') or [])]
        if files.get('details'):
            pages.append(files['details'])
        srt = files.get('transcript') or b.get('transcript')
        text = Path(srt).read_text(encoding='utf-8', errors='replace') if srt and Path(srt).exists() else ''
        return pages, text, None
    import review_bundle
    gate = review_bundle._gate()
    info = gate.probe(Path(video))
    every = review_bundle.sample_every(info['duration'])
    portrait = (info['height'] or 0) > (info['width'] or 0)
    frames = review_bundle.sample_frames(gate.FFMPEG, video, every, 160 if portrait else 256, Path(out) / 'frames')
    pages = [p['file'] for p in review_bundle.pages(frames, Path(out), portrait)]
    return pages, _transcript(video), every


def _ask_codex(exe, prompt, pages, cwd, model, effort):
    args = [exe, 'exec', '--ephemeral', '--ignore-rules', '--skip-git-repo-check', '--sandbox', 'read-only']
    args += ['-m', model] if model else []
    args += ['-c', f'model_reasoning_effort="{effort}"'] if effort else []
    for p in pages:
        args += ['-i', p]
    return ai_clis.run_with_speed(args + ['-'], 'codex', model, runner=_run,
                                  cwd=cwd, timeout=ASK_TIMEOUT, input=prompt, env=ai_clis.child_env())


def _ask_claude(exe, prompt, pages, cwd, model, effort):
    args = [exe, '-p', '--allowedTools', 'Read', '--setting-sources', 'local', '--strict-mcp-config',
            '--no-session-persistence']
    args += ai_clis.claude_instruction_args()
    args += ['--model', model] if model else []
    args += ['--effort', effort] if effort else []
    args += ['--output-format', 'json']      # the answer with its token use: review.json's 'usage', counted in the run's cost
    folders = sorted({str(Path(p).parent) for p in pages} - {str(Path(cwd).resolve())})
    args += ['--add-dir', *folders] if folders else []
    files = ', '.join(pages)
    return ai_clis.run_with_speed(args, 'claude', model, runner=_run, cwd=cwd, timeout=ASK_TIMEOUT, env=ai_clis.child_env(),
                input=f'Look at every one of these image files first, in order: {files}\n\n' + prompt)


ASK = {'claude': _ask_claude, 'codex': _ask_codex}    # one entry per AI


def _ask(engine, exe, prompt, pages, cwd, model=None, effort=None):
    """One separate, read-only run with nothing carried over from another session. The prompt goes in by stdin: a whole
    transcript doesn't fit on a Windows command line."""
    return ASK[engine](exe, prompt, [str(Path(p).resolve()) for p in pages], cwd, model, effort)


def _show_in_panel(request_file, out, project):
    """Ask the letitedit window showing this video to run the review as a visible conversation. Which AI it runs on, or None
    when there's no window that can."""
    import letitedit_instances as inst
    from letitedit_client import ShotcutBridge
    try:
        rows = inst.list_instances()
    except Exception:  # noqa: BLE001 - no window
        return None
    def same(a, b):
        return bool(a and b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    # the video's own window, else the window this run belongs to, else the only one there is
    row = next((r for r in rows if same(r.get('project'), project)), None)         or next((r for r in rows if r['instance_id'] == os.environ.get('LETITEDIT_INSTANCE')), None)         or (rows[0] if len(rows) == 1 else None)
    if not row:
        return None
    try:
        with inst.scope(row['instance_id']), ShotcutBridge(timeout=30) as b:
            answer = b.call('chat_review', {'request': str(request_file), 'out': str(out)})
    except Exception:  # noqa: BLE001 - an older window, or one that went away
        return None
    return answer.get('engine') if answer.get('started') else None


def _visible_review(prompt, pages, out, project, who):
    """Background runs are off: the review happens in front of the person, in the panel. The window starts the program; this
    only hands over the request and waits for the answer file."""
    out = Path(out).resolve()
    review_file = out / 'review.json'
    review_file.unlink(missing_ok=True)
    files = ', '.join(str(Path(p).resolve()) for p in pages)
    request = out / 'critic-request.md'
    request.write_text(f'Look at every one of these image files first, in order: {files}\n\n{prompt}\n\nWhen you have your '
                       f'answer, save the JSON, and nothing else, as this file with your file-writing tool: {review_file}\n',
                       encoding='utf-8')
    # A connector AI reads a picture file as text, so its host attaches the pictures to the message instead (bridge/acp_host.py).
    request.with_suffix('.json').write_text(json.dumps({
        'images': [str(Path(p).resolve()) for p in pages], 'answer': str(review_file),
        'prompts': [f'The pictures of the video are attached to this message, in order.\n\n{prompt}\n\nWhen you have your answer, save '
                    f'the JSON, and nothing else, as this file with your file-writing tool: {review_file}\n']}), encoding='utf-8')
    engine = _show_in_panel(request, out, project)
    if not engine:
        return {'error': 'Background runs of your AI are off, and letitedit could not show the review in a window. Open the '
                         'video in letitedit and run the review again, or turn background runs on in Connect Your AI.', 'error_kind': 'background_off', 'engine': None, 'attempts': []}
    deadline = time.monotonic() + ASK_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(PANEL_POLL_S)
        try:
            found = json.loads(review_file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue       # not there yet, or still being written
        if found.get('error') or 'verdict' in found:
            found.setdefault('attempts', [])
            found.update(engine=engine if 'verdict' in found else None, same_vendor=None if who is None else engine == who,
                         visible=True)
            return found
    return {'error': 'The review could not finish: the review conversation gave no answer. Run it again.',
            'error_kind': 'no_answer', 'engine': None, 'attempts': []}


def _answer(text):
    """The review in an AI's answer, or None."""
    for candidate in reversed(re.findall(r'\{.*\}', text or '', re.S)):
        try:
            found = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(found, dict) and 'verdict' in found:
            return found
    return None


def _nobody(failed, signed_out, tail=''):
    """review.json when no AI could review: what happened and what to do, naming only what is on this PC."""
    limited = [f for f in failed if f['outcome'] == 'limit']
    gone = [f for f in failed if f['outcome'] in ('missing', 'could not start')]
    if gone and not limited:
        name = gone[-1]['engine']
        kind, plain = 'missing', (f"Nobody could review this video: {ai_clis.NAMES[name]}'s program is missing from this PC. An update "
                                  f'may have stopped partway. To reinstall it, {ai_clis.REINSTALL[name]}, then run the review again.')
    elif limited:
        words = limited[-1].get('said') or f"{ai_clis.NAMES[limited[-1]['engine']]} has hit its usage limit."
        kind, plain = 'limit', f'Nobody could review this video yet: {words} Run the review again once it resets.'
    elif failed:
        names = ' or '.join(ai_clis.NAMES[f['engine']] for f in failed)
        kind, plain = 'no_answer', f'The review could not finish: no usable answer came back from {names}. Run it again.'
    elif signed_out:
        names = ' or '.join(ai_clis.NAMES[e] for e in signed_out)
        kind, plain = 'signed_out', (f'Nobody could review this video: {names} on this PC is not signed in. '
                                     'Use Menu > AI > Connect Your AI to sign in, then run the review again.')
    else:
        kind, plain = 'no_ai', ('No AI is set up on this PC, so nobody has reviewed the story, pacing and shots. '
                                'Use Menu > AI > Connect Your AI to set up your AI subscription, then run the review again.')
    return {'error': plain, 'error_kind': kind, 'engine': None, 'attempts': failed, 'tail': tail[-800:]}


def _usage(stdout):
    """(the answer's text, its token use) from `claude -p --output-format json`; plain output comes back as it was."""
    try:
        wrapped = json.loads(stdout)
    except (TypeError, ValueError):
        return stdout, None
    if isinstance(wrapped, dict) and 'result' in wrapped:
        return str(wrapped.get('result') or ''), {k: wrapped.get(k) for k in ('usage', 'total_cost_usd', 'duration_ms',
                                                                              'num_turns') if wrapped.get(k) is not None}
    return stdout, None


def run_review(prompt, pages, out, prefer=None, project=None, tier='person'):
    """Ask the AIs in order until one answers (see the module doc). Always returns what to write in review.json.
    tier='cheap': a panel reviewer, on the AI's cheaper model (panel.CHEAP), not the person's."""
    settings = ai_clis.chat_settings()
    who = ai_clis.editor(settings)
    if not ai_clis.background_allowed(settings):
        return _visible_review(prompt, pages, out, project, who)
    failed, signed_out, tail = [], [], ''
    for engine in ai_clis.critic_order(prefer or os.environ.get('LETITEDIT_CRITIC_ENGINE'), who):
        exe = ai_clis.find(engine, settings)
        if not exe:
            continue          # not on this PC: never mentioned
        if ai_clis.signed_in(engine, exe) is False:
            signed_out.append(engine)
            continue
        same = None if who is None else engine == who
        # a test's forced model and effort, else the person's saved choice for this AI (the other AI too), else Auto's
        # planning role (their model is "auto"), else the app's default for it (ai_clis.choice)
        picked = ai_clis.choice(engine, 'plan', settings, pin={'model': os.environ.get('LETITEDIT_CRITIC_MODEL'),
                                                              'effort': os.environ.get('LETITEDIT_CRITIC_EFFORT')})
        model, effort = picked['model'], picked['effort']
        if tier == 'cheap':
            import panel
            model, effort = panel.CHEAP[engine]
        try:
            # never in the video's folder: under a folder with an AGENTS.md (ours, in a test) a reviewer takes it as instructions
            result = _ask(engine, exe, prompt, pages, tempfile.gettempdir(), model or None, effort or None)
        except subprocess.TimeoutExpired:
            failed.append({'engine': engine, 'outcome': 'timeout'})
            continue
        except OSError as e:
            failed.append({'engine': engine, 'outcome': 'could not start', 'said': str(e)[:200]})
            continue
        text, usage = _usage(result.stdout)
        review = _answer(text)
        if review is not None:
            review.update(engine=engine, model=model or None, effort=effort or None, same_vendor=same, attempts=failed)
            if getattr(result, 'speed_notice', None):
                review['speed_notice'] = result.speed_notice
            if usage:
                review['usage'] = usage
            return review
        printed = f'{result.stdout[-2000:]}\n{result.stderr[-2000:]}'    # the end: an echoed transcript may say anything
        kind = ai_clis.failure_kind(printed)
        failed.append({'engine': engine, 'outcome': kind or 'no answer', 'said': ai_clis.limit_line(printed)})
        tail = printed
    return _nobody(failed, signed_out, tail)


def targeted_prompt(spec):
    """One narrow question after the review rounds have ended: is each open item fixed? No new findings."""
    listed = spec.get('items') or []
    items = '\n'.join(f"- {i['id']} (at {i.get('at') or 'no one moment'}): {i.get('what')}"
                      + (' [the words this finding quotes are no longer in the new export]' if i.get('quote_gone') else '')
                      for i in listed)
    gone = any(i.get('quote_gone') for i in listed)
    return ("You reviewed this video edit earlier and left these findings open. The editor has changed the project since. Look only at "
            "these findings and say, for each, whether it is fixed in the new export. This isn't a new review: don't raise anything "
            "else, and don't judge anything else. Say fixed only if the pictures and words show it; if you can't tell, say still_open.\n"
            f"The findings:\n{items}\n\nThe images are strips and frames around those moments in the new export, labelled with their "
            "findings' moments where they have one, and the whole video's pages when a finding is about no one moment. The words "
            "around them, from a small speech model that mishears names:\n"
            f"{spec.get('words') or '(no speech there)'}\n\n"
            + ("For a finding marked as quoting words the new export no longer has, still_open needs \"now\": the finding as it "
               "stands in the new export, in one line, quoting only words it shows or says.\n\n" if gone else '')
            + "Return JSON only: {\"verdict\": \"targeted\", \"previously\": [{\"id\": \"r1\", \"status\": \"fixed|still_open\", "
            "\"why\": \"what you saw, in one line\"" + (", \"now\": \"...\"" if gone else '') + "}]}, with one entry for each "
            "finding above.")


def run_panel(a, out, got):
    """The panel's review (panel.py): its members' pictures and words from what the bundle made."""
    import panel
    import review_bundle
    bundle = json.loads(Path(a.bundle).read_text(encoding='utf-8-sig')) if a.bundle and Path(a.bundle).exists() else {}
    info = review_bundle._gate().probe(Path(a.video))
    brief = json.loads(got['brief_text']) if got['brief_text'].strip().startswith('{') else {}
    audio = [str(out / 'audio.png')] if (out / 'audio.png').exists() else []
    text_frames = [p for p in [(got['motion'] or {}).get('text_frames')] if p and Path(p).exists()]
    strips = [p for p in got['motion_pages'] if p not in text_frames]
    summary = bundle.get('motion_summary') or {}
    ctx = {'kind': a.kind, 'duration': info['duration'], 'video': a.video,
           'portrait': (info['height'] or 0) > (info['width'] or 0), 'brief_text': got['brief_text'],
           'look_recipe': got['look_recipe'], 'theme': panel.theme_text(brief), 'memory_text': got['memory_text'],
           'plan_text': got['plan_text'], 'questions': ' '.join(f'[{m}] {q}' for m, q in got['questions']),
           'mode_files': [MODES / MODE_FILES[m] for m in got['modes']], 'code_findings': bundle.get('code_findings'),
           'words': got['words'], 'unheard_note': got.get('unheard_note') or '', 'numbers': got['numbers'],
           'motion': summary,
           'pages_for': {'story': got['pages'], 'captions': got['pages'] + text_frames,
                         'sound': audio + got['timing_pages'], 'motion': (strips + text_frames) or got['pages']},
           'extra_for': {'captions': text_frames, 'motion': strips + text_frames},
           'material': {
               'story': f"The {len(got['pages'])} images cover the WHOLE video in time order: contact pages whose tiles are "
                        'labelled with their time, then a page of larger frames at key moments.',
               'captions': 'The images are contact pages of the video in time order (tiles labelled with their time)'
                           + (', then full-size frames of the words on screen' if text_frames else '') + '.',
               'sound': 'The images are the level graph of the whole sound (speech and music levels over time, silences '
                        "marked) and the timing pages (cuts against the music's beats). You cannot hear it: judge from "
                        'these, the measurements and the words, and say nothing about how it sounds.',
               'motion': ('The images are strips of EVERY frame around each arrival and exit (labelled with the time, the '
                          'element and the frames from 4 before to 11 after)' + (', then full-size frames of the words on '
                                                                                  'screen' if text_frames else '')
                          + f". The timing sheet:\n{got['motion_sheet']}" if strips else
                          'The images are contact pages of the video in time order.')}}

    def ask(prompt, pages, tier):
        answer = run_review(prompt, pages, out, a.engine, a.project, tier=tier)
        info_ = {k: answer.get(k) for k in ('engine', 'model', 'effort', 'same_vendor', 'usage') if answer.get(k) is not None}
        return answer, info_
    return panel.run(ctx, ask, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--kind', choices=['short', 'long'], required=True)
    ap.add_argument('--brief', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--engine', choices=['codex', 'claude'])
    ap.add_argument('--bundle')
    ap.add_argument('--story-plan')
    ap.add_argument('--project')
    ap.add_argument('--memory')
    ap.add_argument('--targeted', help="a JSON file: {items, pictures, words}: only say whether each item is fixed (see targeted_prompt)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.targeted:
        spec = json.loads(Path(a.targeted).read_text(encoding='utf-8-sig'))
        look = run_review(targeted_prompt(spec), spec.get('pictures') or [], out, a.engine, a.project)
        (out / 'targeted-look.json').write_text(json.dumps(look, indent=1), encoding='utf-8')
        print(json.dumps({k: look.get(k) for k in ('verdict', 'previously', 'error')}))
        return
    pages, words, every = material(a.video, a.kind, out, a.bundle)
    checks = out / 'checks.json'
    numbers = {}
    if checks.exists():
        data = json.loads(checks.read_text(encoding='utf-8-sig'))
        numbers = {c['check']: c['value'] for c in data['checks']}
        # measured but not judged for this kind of video (a mode's pace checks that are off): still facts
        numbers.update({o['check']: o['value'] for o in data.get('off') or [] if o.get('value') is not None})
    craft = out / 'craft-facts.json'        # T346, written only while review_craft_checks is on
    if craft.exists():
        import letitedit.review.craft_checks as craft_checks
        numbers = craft_checks.critic_numbers(numbers, json.loads(craft.read_text(encoding='utf-8-sig')))
    overlay = out / 'overlay-facts.json'    # T352, written only while studio_overlay_facts is on (a Studio job)
    if overlay.exists():
        numbers.update(json.loads(overlay.read_text(encoding='utf-8-sig')))
    timing, timing_pages = {}, []
    if (out / 'timing.json').exists():      # the bundle's rhythm map and music sync (measured, frame-accurate)
        timing = json.loads((out / 'timing.json').read_text(encoding='utf-8-sig'))
        timing.pop('warnings', None)
    motion = {}
    hearing = None
    if a.bundle and Path(a.bundle).exists():
        bundle_data = json.loads(Path(a.bundle).read_text(encoding='utf-8-sig'))
        hearing = bundle_data.get('hearing')
        timing_pages = [p for p in bundle_data.get('timing_images') or [] if Path(p).exists()]
        motion = bundle_data.get('motion') or {}
    motion_pages = [p for p in (motion.get('strips') or []) + [motion.get('text_frames')] if p and Path(p).exists()]
    motion_sheet = (Path(motion['sheet']).read_text(encoding='utf-8', errors='replace')[:MOTION_SHEET_MAX]
                    if motion.get('sheet') and Path(motion['sheet']).exists() else '')
    deep = os.environ.get('LETITEDIT_CRITIC_DEPTH') == 'deep'
    if len(words) > TRANSCRIPT_MAX and not deep:     # a long video: the same words and start times, without SRT's numbers and end times
        words = compact_srt(words)
    if len(words) > TRANSCRIPT_MAX and not deep:
        words = words[:TRANSCRIPT_MAX] + f'\n[... transcript continues; {len(words) - TRANSCRIPT_MAX} characters not shown]'
    plan, plan_from = find_story_plan(a.story_plan, a.project, a.brief, a.bundle, out)
    plan_text = plan_summary(plan, a.kind) if plan else ''
    brief_text = Path(a.brief).read_text(encoding='utf-8-sig')
    try:
        modes = brief_modes(json.loads(brief_text))
    except (ValueError, AttributeError):
        modes = []
    questions = mode_questions(modes)
    try:
        look_recipe = json.loads(brief_text).get('look_recipe')
    except (ValueError, AttributeError):
        look_recipe = None
    memory_text = Path(a.memory).read_text(encoding='utf-8') if a.memory and Path(a.memory).is_file() else ''
    prompt = (
        f"You are a picky senior editor reviewing a {a.kind} video edit for a creator. Judge only what you can point "
        f"to. The brief:\n{brief_text}\n\n"
        + (f"{memory_text}\n\n" if memory_text else '')
        + (f"The person chose a Look for this video: the brief's `look` field. Its recipe follows. What the recipe asks for "
           f"(its captions, its framing, its effects, its sounds, its few moving pictures) is intended: do not flag it as a "
           f"defect. Do flag where the render breaks the recipe (including its 'Must not' list), where the Look was "
           f"applied badly, or where the footage did not suit it and the edit forced it. A recipe describes a result "
           f"from one sample clip, so its numbers are examples, not limits.\n{look_recipe}\n\n"
           if look_recipe else '')
        + (f"The editor's story plan (what the edit set out to do; where it differs from the brief, the brief wins). "
           f"Say whether the render delivers each section's purpose, and where it drifts:\n{plan_text}\n\n"
           if plan_text else '')
        + (f"Kind of video: {', '.join(modes)} (the first leads). Answer these questions for it, each with evidence: "
           + ' '.join(f'[{m}] {q}' for m, q in questions) + "\nJudge pace against the brief's feel and reference and "
           "this kind of video, not against a fixed idea that Shorts must be fast or documentaries slow.\n\n"
           if questions else '')
        + f"The {len(pages)} images cover the WHOLE video in time order: contact pages whose tiles are labelled with "
        f"their time (left to right, top to bottom, page after page)"
        f"{', then one page of larger frames at key moments' if len(pages) > 1 else ''}. Look at every page. "
        + transcript_text(words, hearing)
        + f"Measurements: {json.dumps(numbers)}\n\n"
        + (f"Timing measured frame by frame (cut rate, shot lengths, cuts on action and on the beat, motion, per "
           f"section; music sync: offsets from the beat against chance). These are facts, not verdicts: use them to "
           f"judge pacing and music fit, and say where they agree or disagree with what you see"
           + (f"; the last {len(timing_pages)} image(s) are its timing pages" if timing_pages else '')
           + f":\n{json.dumps(timing, default=str)[:6000]}\n\n" if timing else '')
        + (f"This video is dense ({motion.get('events_per_s')} events a second: cuts, graphics and motion arriving and "
           f"leaving, sound effects). After the pages come {len(motion_pages)} image(s) of its motion: strips of EVERY frame "
           f"around each arrival and exit (labelled with the time, the element and the frames from 4 before to 11 after)"
           + (", then full-size frames of the words on screen" if motion.get('text_frames') else '')
           + ". Judge from them how each element arrives, settles and leaves: whether it pops in on one frame, overshoots, "
           "is still moving when it should be read, competes with another for the eye, or covers a caption or the apps' "
           "buttons. Over a face, weigh it: a note when it could sit elsewhere, nothing when the Look or the moment calls "
           "for it. The code has already measured, on the timeline, landing on the word, reading time, how many arrive "
           "at once, impact sounds against their picture, stutter and flashes; its findings are in the review already, so "
           "don't repeat them: add only what the frames show. You can't hear the sound effects: say nothing about how they "
           f"sound. The timing sheet:\n{motion_sheet}\n\n" if motion_pages or motion_sheet else '')
        + "Consider story (can you retell it; does it keep its promise), pacing, shot choice, sound (from the "
        "transcript and measurements), on-screen text and captions (readable, correct, not covering the action), and "
        "every requirement in the brief. A caption or graphic that looks faint on one tile may be caught mid-fade: call it dim "
        "only if it stays dim across the tiles of its whole time on screen. Severity: critical = should not be published as it is "
        "(a broken promise, a required moment missing, wrong or unreadable key text, a glaring technical fault); major = a viewer "
        "would notice it and it hurts the video; minor = polish, or something a viewer would not notice. List every evidence-backed "
        "problem with its time; finding none is a valid answer. Say who can fix each: owner = \"person\" only if it needs something "
        "only the person has (a real recording of the software, proof of a number, the real link or a fact to verify, or their "
        "decision); owner = \"ai\" for anything the edit itself can change with the footage it has (cuts, pacing, captions, framing, "
        "sound, graphics, an honest illustration). "
        "Return JSON only: {\"verdict\": \"block|revise|ok-with-notes|ok\", \"retell\": \"what it is about and what "
        "it leaves the viewer with, in one sentence (for a goal story: goal, obstacle and change), or 'cannot'\", "
        "\"promise_paid\": true|false, \"checked\": \"which pages and time ranges "
        "you looked at\", \"problems\": [{\"rank\": 1, \"t\": \"m:ss\", \"severity\": \"critical|major|minor\", "
        "\"kind\": \"story|pacing|shots|sound|text|technical|brief\", \"owner\": \"ai|person\", \"evidence\": \"...\", "
        "\"fix\": \"...\"}], \"previously\": [{\"id\": \"r1\", \"status\": \"fixed|still_open\"}]}. `previously` answers the list of "
        "earlier findings, if there is one.")
    pages = list(pages) + motion_pages + timing_pages
    if os.environ.get('LETITEDIT_CRITIC_DEPTH') == 'panel' and ai_clis.background_allowed(ai_clis.chat_settings()):
        review = run_panel(a, out, {'pages': pages[:len(pages) - len(motion_pages) - len(timing_pages)], 'words': words,
                                    'unheard_note': unheard_note(words, hearing) if words.strip()
                                    else transcript_text(words, hearing).strip(),
                                    'numbers': numbers, 'timing_pages': timing_pages, 'motion_pages': motion_pages,
                                    'motion_sheet': motion_sheet, 'motion': motion, 'brief_text': brief_text,
                                    'memory_text': memory_text, 'look_recipe': look_recipe, 'plan_text': plan_text,
                                    'questions': questions, 'modes': modes})
    else:
        review = run_review(prompt, pages, out, a.engine, a.project)
    review['pages_shown'] = len(pages)
    review['story_plan'] = plan_from
    review['modes'] = modes
    review['mode_questions'] = [m for m, _ in questions]
    (out / 'review.json').write_text(json.dumps(review, indent=1), encoding='utf-8')
    print(json.dumps({k: review.get(k) for k in ('verdict', 'retell', 'promise_paid', 'pages_shown')}))


if __name__ == '__main__':
    main()
