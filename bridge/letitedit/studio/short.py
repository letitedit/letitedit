"""The `short` kind for real: one vertical video from an idea, made by New video's own path (CONTRACT.md section 6,
"short").

The job runs what the person gets when they press New video: the same dialog, the same request, the same stages,
skills, review rounds and checks, in a hidden editor window of the job's own
(window.py), never the person's. The Studio adds nothing to the edit itself: what the job asks for (the idea, the
footage, the rules, the brand kit, the music policy) goes into New video's "What it's about" box, as a person would
type it, and the Studio makes the delivered files from the finished video afterwards.

    preview   prepare, log, story, rough, proxy: New video stops after the rough cut (its window runs with
              LETITEDIT_NEW_VIDEO_STOP_AFTER=rough, so the rough stage's done note asks for a hand-over and the end of
              the turn: app/new_video_stages.py); the rough cut is exported and given as the phone proxy, with draft
              captions from the timeline's own words. No review, no platform files.
    final     from a preview (from_job): prepare (the preview's project copied into this job's folder, its paths
              rewritten), fine, finish, review, export, proxy. New video goes on from the hand-over in a fresh
              conversation, with the app's own next-stage message (new_video_stages.fresh_request), sent the way the app
              sends a New video that waited (learnlooks.h: a pending-video.json with its save folder).
    final     without from_job: prepare, log, story, rough, fine, finish, review, export, proxy, in one run.

The export stage makes each platform's file from the AI's final export (delivery.py): under its size cap, the overlay
items applied to it, through the location stripper, checked SDR. Then the result is read from the project's own files:
text items and choices from the timeline, provenance from its clips, the review from the review bundle, the cost from
the AI's session logs (run_cost.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import letitedit.studio.delivery as delivery
import letitedit.studio.files as files
import letitedit.studio.licences as licences
import letitedit.studio.receipts as receipts
import letitedit.studio.state as state

END_CONFIRM_S = 5            # the end signal (final_receipts and session_ended) held this long: the run has ended
IDLE_DONE_S = 60             # fallback: the receipts complete and the window not busy, but not saying its run ended
UNSURE_DONE_S = 180          # fallback: the window's state unreadable, or the review looks unfinished
STALLED_S = 20 * 60          # the AI idle this long with its stage not done: it stopped
STOP_WAIT_S = 600            # a preview: how long the AI has to end its turn after the rough cut
POLL_S = 3.0
RUN_FILE = 'short-run.json'
REQUEST_FILE = 'studio-request.txt'
PREPARED_PROJECT_ENV = 'LETITEDIT_NEW_VIDEO_PREPARED_PROJECT'
SOURCES_FILE = 'studio-sources.json'      # beside the project: the footage New video was given (copied with it)
SDR_DIR = '_footage'                        # in the job's work folder: SDR working copies of HLG footage
COPIES_FILE = 'studio-copies.json'          # which original each working copy was made from
PREVIEW_STOP = 'rough'
STAGE_ORDER = ('log', 'story', 'rough', 'fine', 'finish')
HOOK_KINDS = {'question': 'question', 'result_first': 'result_first', 'mid_action': 'mid_action',
              'number': 'number_or_list', 'stakes': 'story_tease', 'quote': 'other'}
AUDIO_EXT = ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.opus', '.aac')
MUSIC_SOURCES = (('music-library', 'letitedit_library'), ('starter-music', 'letitedit_library'),
                 ('written-music', 'written'), ('youtube-audio', 'youtube_audio_library'), ('pixabay', 'pixabay'))
# A music track's `source` (contract: music.tracks) -> the choices' `music_kind`, which has its own words.
MUSIC_KINDS = {'letitedit_library': 'library', 'youtube_audio_library': 'library', 'pixabay': 'library',
               'written': 'written', 'ai_made': 'ai_made', 'person_file': 'person_file',
               'in_source_footage': 'in_source_footage'}
_WINDOWS = {}                # job id -> its StudioWindow, while this process runs it


# ------------------------------------------------------------------ the plan

def tier_of(job):
    return (job.get('inputs') or {}).get('tier') or 'final'


def stages(job):
    if tier_of(job) == 'preview':
        return [('prepare', prepare), ('log', _waiter('log')), ('story', _waiter('story')),
                ('rough', _waiter('rough')), ('proxy', preview_result)]
    if job.get('from_job'):
        return [('prepare', prepare_from), ('fine', _waiter('fine')), ('finish', _waiter('finish')),
                ('review', wait_review), ('export', export_files), ('proxy', final_result)]
    return [('prepare', prepare), ('log', _waiter('log')), ('story', _waiter('story')), ('rough', _waiter('rough')),
            ('fine', _waiter('fine')), ('finish', _waiter('finish')), ('review', wait_review),
            ('export', export_files), ('proxy', final_result)]


def _run_path(ctx):
    return Path(ctx.dir) / RUN_FILE


def _run(ctx):
    return files.read_json(_run_path(ctx)) or {}


def _save_run(ctx, run):
    files.write_json(_run_path(ctx), run)


def _begin_attempt(run):
    """An attempt of this job's AI starts now (a first start, or a retry after a failure or a stop). `since` is the
    start of this attempt, which the exports and receipts are read from; `first_since` stays the first attempt's start
    and `attempts` counts them, so the cost counts every attempt (T305 fault 6: after a retry only the last one)."""
    now = time.time()
    made = int(run.get('attempts') or (1 if run.get('since') else 0))
    if not run.get('first_since'):
        run['first_since'] = run.get('since') or now
    run['attempts'] = made + 1
    run['since'] = now


def _home():
    import letitedit.studio.service as service
    return service.home()


# ------------------------------------------------------------------ the footage

def _ledger_moment(home, moment_id):
    """(paths, in, out) of a moment the Studio's index minted, or None."""
    import letitedit.studio.library as library
    for f in sorted(library.ledger_dir(home).glob('f_*.json')):
        ledger = files.read_json(f) or {}
        for m in ledger.get('moments') or []:
            if m.get('moment_id') == moment_id:
                return ledger.get('paths') or [], m['in'], m['out']
    return None


def resolve_sources(job, home):
    """{'mode': pieces|find_in|none, 'files': [paths], 'folder', 'ranges': [(path, in, out, moment_id)], 'avoid'}."""
    src = (job.get('inputs') or {}).get('sources') or {}
    if src.get('none'):
        return {'mode': 'none', 'files': [], 'folder': None, 'ranges': [], 'strict': False}
    if src.get('pieces'):
        ranges = []
        for piece in src['pieces']:
            mid = piece.get('moment_id')
            path, a, b = piece.get('path'), piece.get('in'), piece.get('out')
            if mid and not path:
                got = _ledger_moment(home, mid)
                if not got or not got[0]:
                    raise state.StudioError('source_missing', f'The moment {mid} is not in this letitedit\'s index. '
                                            'Index its folder first, or give the file and times.', stage='prepare')
                path = next((p for p in got[0] if Path(p).is_file()), got[0][0])
                a, b = (got[1] if a is None else a), (got[2] if b is None else b)
            ranges.append((str(path), a, b, mid))
        paths = sorted({r[0] for r in ranges}, key=str.lower)
        return {'mode': 'pieces', 'files': paths, 'folder': _common_folder(paths), 'ranges': ranges,
                'strict': src.get('strict', True)}
    folders = [str(Path(f)) for f in src.get('find_in') or []]
    return {'mode': 'find_in', 'files': [], 'folder': _common_folder(folders, folders=True), 'ranges': [],
            'strict': False, 'folders': folders, 'hint': src.get('hint'), 'avoid': src.get('avoid_moments') or []}


def _common_folder(paths, folders=False):
    if not paths:
        return None
    dirs = [str(Path(p)) if folders else str(Path(p).parent) for p in paths]
    try:
        return os.path.commonpath(dirs)
    except ValueError:                                 # on different drives
        return None


def check_sources(srcs):
    """Every footage file there and readable, and none HDR of a kind letitedit can't render (the HDR rule)."""
    import letitedit.studio.library as library
    paths = list(srcs['files'])
    if srcs['mode'] == 'find_in':
        missing = [f for f in srcs['folders'] if not Path(f).is_dir()]
        if missing:
            raise state.StudioError('source_missing', 'A footage folder is not there (moved, renamed, or on a drive '
                                    'that is not connected): ' + '; '.join(missing), stage='prepare')
        paths = [str(p) for p in library.media_files(srcs['folders']) if library.kind_of(p) == 'video']
        if not paths:
            raise state.StudioError('no_footage_for_idea', 'The footage folders hold no video.', stage='prepare')
    for p in paths:
        if not Path(p).is_file():
            raise state.StudioError('source_missing', f'A footage file is not there: {p}', stage='prepare')
    if srcs['mode'] != 'none' and not srcs['folder']:
        raise state.StudioError('source_unreadable', "New video takes footage from one drive: these files are on "
                                'different drives. Copy them to one folder first.', stage='prepare')
    refused = []
    for p in paths:
        info = delivery.probe(p)
        if info is None:
            raise state.StudioError('source_unreadable', f'A footage file could not be read: {p}', stage='prepare')
        if info.get('width') and info.get('hdr') in ('pq', 'unknown'):
            refused.append((p, info['hdr']))
    if refused:
        names = '; '.join(f"{Path(p).name} ({'PQ (HDR10)' if k == 'pq' else 'wide-colour HDR'})" for p, k in refused)
        raise state.StudioError('hdr_not_supported', 'letitedit makes SDR videos and cannot yet turn PQ (HDR10) '
                                f'footage into SDR faithfully: {names}. Export these clips as SDR (or HLG, which '
                                'phones such as the iPhone record) and send the job again.', stage='prepare')
    return paths


def _norm(path):
    return os.path.normcase(os.path.normpath(str(path)))


def _all_media(srcs):
    import letitedit.studio.library as library
    if srcs['mode'] == 'find_in':
        return [str(p) for p in library.media_files(srcs['folders'])]
    return list(srcs['files'])


def sdr_footage(job_dir, srcs, check=lambda: None):
    """The HDR rule for New video (delivery.py): when any of the job's footage is HLG (or wide colour with an SDR
    transfer), New video edits SDR working copies instead, made in the job's own folder (work/_footage), with the
    files that need no tone map linked or copied beside them so New video still takes one folder. The person's footage
    is only read. Returns srcs, changed to the copies, with `originals` {copy: original} and `tonemapped` [copies]
    (the result names the originals). A copy already whole (a resumed job) is kept."""
    if srcs['mode'] == 'none':
        return srcs
    paths = _all_media(srcs)
    hdr = []
    for p in paths:
        info = delivery.probe(p) or {}
        if info.get('width') and delivery.needs_tonemap(info):
            hdr.append(p)
    if not hdr:
        return srcs
    root = Path(srcs['folder'])
    dst_root = Path(job_dir) / 'work' / SDR_DIR
    need = sum(Path(p).stat().st_size for p in paths) * 1.3
    dst_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(dst_root).free < need:
        raise state.StudioError('disk_full', f'Some footage is HDR (HLG), which letitedit edits from SDR copies in the '
                                f'job folder; that needs about {need / 1e9:.1f} GB free there.', stage='prepare')
    plan = _copy_names(paths, hdr, root, dst_root)
    # the names are reserved before any file is made, and a copy left by an earlier attempt is kept only when the
    # saved mapping says it was made from this same file (path, size and time)
    book = dst_root / COPIES_FILE
    before = files.read_json(book) or {}
    now = {str(dst): {'from': _norm(p), 'id': _identity(p)} for p, dst in plan.items()}
    for dst, rec in now.items():
        if Path(dst).exists() and before.get(dst) != rec:
            Path(dst).unlink()
    files.write_json(book, now)
    originals, mapped, tonemapped = {}, {}, []
    for p in paths:
        check()
        dst = plan[p]
        if p in hdr:
            if not dst.is_file():
                delivery.sdr_copy(p, dst)
            tonemapped.append(str(dst))
        else:
            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(p, dst)
                except OSError:
                    shutil.copy2(p, dst)
        originals[str(dst)] = str(p)
        mapped[_norm(p)] = str(dst)
    out = dict(srcs, folder=str(dst_root), originals=originals, tonemapped=tonemapped,
               files=[mapped[_norm(p)] for p in srcs['files']],
               ranges=[(mapped.get(_norm(r[0]), r[0]), *r[1:]) for r in srcs['ranges']])
    if srcs['mode'] == 'find_in':
        out['folders'] = [str(dst_root)]
    return out


def _identity(p):
    st = os.stat(p)
    return [st.st_size, st.st_mtime_ns]


def _copy_names(paths, hdr, root, dst_root):
    """{original: working copy}: a file needing no tone map at its own relative path, a tone-mapped one at its
    relative path with its own extension kept in the name ('clip.mov' -> 'clip.mov.sdr.mp4'), so two files differing
    only in extension never share a copy; any name still taken gets a short hash of its original's path."""
    plan, taken = {}, set()
    for p in paths:
        rel = Path(os.path.relpath(p, root))
        dst = dst_root / rel.parent / (rel.name + '.sdr.mp4') if p in hdr else dst_root / rel
        if _norm(dst) in taken:
            h = hashlib.sha1(_norm(p).encode()).hexdigest()[:8]
            dst = dst.with_name(f'{dst.stem}-{h}{dst.suffix}')
        taken.add(_norm(dst))
        plan[p] = dst
    return plan


def original_of(srcs, path):
    """The person's file a clip of the edit came from (the clip itself unless it is an SDR working copy), and
    whether it was tone-mapped."""
    srcs = srcs or {}
    for copy, orig in (srcs.get('originals') or {}).items():
        if _norm(copy) == _norm(path):
            return orig, any(_norm(t) == _norm(path) for t in srcs.get('tonemapped') or [])
    return str(path), False


# ------------------------------------------------------------------ what the job asks, as the person would type it

def _said(text):
    """A sentence: text with a full stop unless it already ends in one (or ! ? or a closing quote after one)."""
    text = str(text).strip()
    return text if text.rstrip('"\'').endswith(('.', '!', '?')) else text + '.'


def _notes_list(notes):
    """notes_for_final as a list of notes (the contract gives one string; a list is taken too)."""
    if not notes:
        return []
    return [str(n) for n in notes if str(n).strip()] if isinstance(notes, list) else [str(notes)]


PREFER_ORDER = ("The preferences below rank under every Must and Never line: follow each one unless it conflicts with "
                "a Must or Never line, and when two preferences conflict, the earlier one in this list wins.")
PREFER_BRIEF = ("A preference is a wish, not a requirement: put them in the brief as `preferences`, never in must_keep, "
                "must_avoid or another field the review checks.")
PREFER_NOTE = ("A preference that gave way to another rule is `not_applicable` and its line starts "
               "`gave way to <that rule's id>`.")


def _rule_line(r):
    word = {'must': 'Must', 'never': 'Never', 'prefer': 'Prefer'}.get(r.get('kind'), 'Rule')
    text = r.get('text') or r.get('id')
    return _said(text if text.lower().startswith(word.lower() + ' ') else f'{word}: {text}')


def _prefers(rules):
    return [r for r in rules or [] if r.get('kind') == 'prefer']


def gave_way_to(rule, reason, rules):
    """A prefer's `gave way to <id>, <id>` reason as the ids of the job's other rules it names (contract 1.5)."""
    m = re.search(r'gave way to\s+(.+)', str(reason or ''), re.I)
    if not m or rule.get('kind') != 'prefer':
        return []
    ids = {r['id'] for r in rules or [] if r.get('id') and r['id'] != rule.get('id')}
    named = [x.strip('.()`"\'') for x in re.findall(r'[^\s,;:]+', m.group(1))]
    return list(dict.fromkeys(x for x in named if x in ids))


def final_rules_text(rules):
    """The final's line on the rules it was given (a final from a preview may change them)."""
    text = 'The rules for this final: ' + '; '.join(
        f"{r.get('kind', 'rule')}: {r.get('text') or r['id']}" for r in rules) + '.'
    if _prefers(rules):
        text += (' The prefer rules rank under every must and never rule: follow each one unless it conflicts with a '
                 'must or never rule, and when two prefer rules conflict, the earlier one in this list wins. '
                 + PREFER_BRIEF)
    return text


def about_text(job, srcs, notes=None):
    """New video's 'What it's about' box: the idea, the footage to use, the rules, the brand kit, music and captions,
    in plain words. The Studio's own asks (the rule notes, the post text) are one line each at the end."""
    inp = job.get('inputs') or {}
    idea = inp.get('idea') or {}
    out = []
    head = idea.get('title') or ''
    if idea.get('about'):
        out.append(_said(f"{head + ': ' if head else ''}{idea['about']}"))
    elif head:
        out.append(head)
    if idea.get('hook_line'):
        out.append(f'Open on this hook: "{idea["hook_line"]}"')
    if idea.get('on_screen_text'):
        words = idea['on_screen_text'] if isinstance(idea['on_screen_text'], list) else [idea['on_screen_text']]
        out.append('On-screen text to use: ' + '; '.join(f'"{w}"' for w in words) + '.')
    if idea.get('pattern'):
        out.append(f"The pattern: {idea['pattern']}.")
    if idea.get('end_with'):
        out.append(_said(f"End with: {idea['end_with']}"))
    if srcs['ranges']:
        parts = '; '.join(f'{Path(p).name} {a:g}-{b:g} s' if a is not None and b is not None else Path(p).name
                          for p, a, b, _ in srcs['ranges'])
        out.append(('Use only these parts of the footage: ' if srcs['strict'] else 'Start from these parts of the '
                    'footage: ') + parts + '.')
    if srcs.get('hint'):
        out.append(f"What to look for in the footage: {srcs['hint']}.")
    if srcs.get('avoid'):
        out.append('Leave out these moments, used before: ' + ', '.join(srcs['avoid']) + '.')
    rules = inp.get('rules') or []
    out.extend(_rule_line(r) for r in rules if r.get('kind') != 'prefer')
    if _prefers(rules):
        out.append(PREFER_ORDER + ' ' + PREFER_BRIEF)
        out.extend(_rule_line(r) for r in _prefers(rules))
    kit = inp.get('brand_kit') or {}
    for key, words in (('intro', 'Start with my intro clip'), ('end_card', 'End with my end card'),
                       ('logo', 'My logo'), ('handle', 'My handle')):
        if kit.get(key):
            out.append(f'{words}: {kit[key]}.')
    if kit.get('colours'):
        out.append('My colours: ' + ', '.join(map(str, kit['colours'])) + '.')
    if kit.get('fonts'):
        out.append('My fonts: ' + ', '.join(map(str, kit['fonts'])) + '.')
    music = inp.get('music') or {}
    if music:
        bits = []
        if music.get('mode') == 'none':
            bits.append('no music')
        if music.get('allowed_sources'):
            bits.append('music only from ' + ', '.join(music['allowed_sources']).replace('_', ' '))
        if music.get('attribution_ok') is False:
            bits.append('no music that needs a credit')
        if music.get('content_id') == 'must_be_clear':
            bits.append('no music registered with Content ID')
        if bits:
            out.append('Music: ' + '; '.join(bits) + '.')
    if inp.get('captions') == 'none':
        out.append('No captions.')
    if notes:
        out.append('My notes on the preview, for this final: ' + ' '.join(_said(n) for n in _notes_list(notes)))
    if inp.get('overlay_text'):
        out.append("letitedit adds my overlay words to each platform's file after the export: don't add them."
                   + overlay_facts_text(job))
    if inp.get('rules'):
        ids = ', '.join(r['id'] for r in inp['rules'])
        if _prefers(inp['rules']):                     # a prefer names the rule it gave way to by id
            ids = '; '.join(f"{r['id']} = {r.get('kind', 'rule')}: {r.get('text') or r['id']}" for r in inp['rules'])
        out.append(f'When the review is done, add one journal note per rule ({ids}), each '
                   '`rule:<id>: applied|not_applicable|not_met|could_not_check: <one plain line> @<start>-<end>` '
                   '(the times where it applies in the final video, seconds).'
                   + (' ' + PREFER_NOTE if _prefers(inp['rules']) else ''))
    if (inp.get('deliver') or {}).get('post_text'):
        out.append('At the end add a journal note `post_text: <a suggested caption for the post, one line>`.')
    return '\n'.join(out)


def overlay_facts_on():
    """T352's switch (settings.json studio_overlay_facts, on by default; LETITEDIT_STUDIO_OVERLAY_FACTS wins)."""
    import letitedit.review.overlay_clash as overlay_clash
    return overlay_clash.enabled()


def overlay_items(job, run=None):
    """[{text, from, placement, platform, frame, box, if, note}]: where each overlay item goes on each platform's
    file, laid out as export_files lays it out (delivery.overlay_layout) before any face is known; box None for an
    item in the Look's caption zone (not known before the Look is drawn) or one that can't be placed. An item with
    conditions (`if`) is laid out with the others it would join."""
    import letitedit.studio.capabilities as capabilities
    import letitedit.studio.overlays as overlays
    run = run or {}
    given = overlays.items(job)
    if not given and run.get('from'):
        given = overlays.carried((files.read_json(Path(run['from']) / 'result.json') or {}).get('text_items'))
    if not given:
        return []
    presets = {p['id']: p for p in capabilities.platforms_list()}
    out = []
    for plat in [p['id'] for p in _platforms(job, run)]:
        preset = presets.get(plat) or {}
        width, height = int(preset.get('width') or 1080), int(preset.get('height') or 1920)
        if width > height:                  # a landscape platform gets no file of a Short (export_files refuses it)
            continue
        chosen = [(f, it) for f, it in given if not it.get('platforms') or plat in it['platforms']]
        plain = [(f, it) for f, it in chosen if not it.get('if')]
        laid = {}
        for group in (plain, chosen):
            spots = delivery.overlay_layout([(it['text'], it.get('placement') or 'safe_area') for _, it in group],
                                            plat, width, height)
            for (f, it), (_, _, _, box, used, note) in zip(group, spots):
                laid.setdefault(f, (box, used, note))
        for f, it in chosen:
            box, used, note = laid[f]
            placement = it.get('placement') or 'safe_area'
            if placement == 'caption_zone':
                box, note = None, "in the Look's caption zone, where its captions are drawn (else the safe area)"
            entry = {'text': it['text'], 'from': f, 'placement': placement, 'platform': plat,
                     'frame': [width, height], 'box': box}
            if it.get('if'):
                entry['if'] = list(it['if'])
            if note:
                entry['note'] = note
            out.append(entry)
    return out


def overlay_facts_text(job, run=None):
    """T352, with its switch on: the request's facts about where each overlay item goes, as boxes in pixels."""
    if not overlay_facts_on():
        return ''
    import letitedit.review.overlay_clash as overlay_clash
    try:
        items = overlay_items(job, run)
    except Exception:  # noqa: BLE001 - no boxes known: the request says what it always said
        return ''
    by_item = {}
    for it in items:
        by_item.setdefault(it['from'], []).append(it)
    parts = []
    for group in by_item.values():
        it = group[0]
        cond = ', only when the video has AI-made picture or sound' if it.get('if') else ''
        where = '; '.join(f"{_platform_name(g['platform'])} {overlay_clash.plain_box(g['box'], g['frame'])}"
                          if g.get('box') else f"{_platform_name(g['platform'])} {g.get('note') or 'not placed'}"
                          for g in group)
        parts.append(f'"{it["text"]}" ({it["placement"].replace("_", " ")}{cond}): {where}')
    if not parts:
        return ''
    w, h = items[0]['frame']
    return (f' Where letitedit puts them, as boxes in the {w}x{h} frame (x from the left, y from the top, in pixels), '
            'for the whole video; nothing of the video shows through a box, and a box moves down past a face that '
            'would be under it: ' + '; '.join(parts) + '.')


def _platform_name(pid):
    try:
        import letitedit.studio.capabilities as capabilities
        return next((p['name'] for p in capabilities.platforms_list() if p['id'] == pid), pid)
    except Exception:  # noqa: BLE001
        return pid


def write_overlay_boxes(job, run, project):
    """T352, with its switch on: the overlay boxes beside the project, for the review (overlay_clash.findings)."""
    if not project or not overlay_facts_on():
        return None
    import letitedit.review.overlay_clash as overlay_clash
    try:
        items = overlay_items(job, run)
    except Exception:  # noqa: BLE001 - no boxes: the review states none
        return None
    if not items:
        return None
    return overlay_clash.write_boxes(project, items, tuple(items[0]['frame']),
                                     note='laid out before the video is made, with no face known; letitedit '
                                          "draws each on the platform's file after the export")


def length_text(job):
    t = ((job.get('inputs') or {}).get('idea') or {}).get('target_seconds')
    return f'{int(round(float(t)))} s' if t else ''


# ------------------------------------------------------------------ driving New video

def _lane(job):
    import letitedit.studio.validate as validate
    return validate.lane(job)


def _window(ctx, job, job_dir, run, stop_after=None):
    import letitedit.studio.window as window
    env = {'LETITEDIT_NEW_VIDEO_STOP_AFTER': stop_after} if stop_after else {}
    if run.get('prepared_project'):
        env[PREPARED_PROJECT_ENV] = run['prepared_project']
    w = window.StudioWindow(_home(), job, job_dir, _lane(job), env=env)
    w.start()
    _WINDOWS[job['job_id']] = w
    return w


def save_window(job, job_dir, stage, project):
    """Save the Studio's own hidden window into its project before it closes. The AI never saves a window (a person's
    window is theirs), so its fine cut, captions and music would stay in the window and close with it, and the result,
    the SRT and the project handed on would be read from the last saved file (the rough cut). Returns the saved path,
    or None (no window, or the save failed: said in an event, and the saved file is read as it is)."""
    w = _WINDOWS.get(job['job_id'])
    if w is None or not w.alive():
        return None
    try:
        shown = (w.call('state') or {}).get('project')
        if not project or not shown or _norm(shown) != _norm(project):
            state.event(job_dir, job, 'progress', stage=stage,
                        message=f"The window shows {Path(shown).name if shown else 'no project'}, not the video's "
                                "project, so it was not saved; the project is read as last saved.")
            return None
        got = w.call('save', {'path': str(project)}, timeout=120) or {}
        return got.get('saved')
    except Exception as e:  # noqa: BLE001 - the window's own message says why
        state.event(job_dir, job, 'progress', stage=stage,
                    message=f"letitedit could not save the window's project before closing it: {str(e)[:300]}")
        return None


def close_window(job):
    w = _WINDOWS.pop(job['job_id'], None)
    if w is not None:
        w.close()
        return
    import letitedit.studio.window as window
    window.StudioWindow(_home(), job, '.', 'dev').close_stale()


def _project_folder(projects, since):
    """The folder New video made for this video under the job's projects folder (created after `since`)."""
    best = None
    for d in Path(projects).iterdir() if Path(projects).is_dir() else []:
        if d.is_dir() and d.stat().st_ctime >= since - 5 and (best is None or d.stat().st_ctime > best.stat().st_ctime):
            best = d
    return best


def _step(w, number, timeout=60):
    """Wait until the dialog shows 'Step <number> of 5'; a step that never comes is a letitedit fault."""
    if not w.wait_for(lambda: f'Step {number} of 5' in str((w.peek('newVideoStep') or {}).get('text') or ''),
                      timeout, 0.5):
        raise state.StudioError('internal', f"New video's dialog did not reach step {number} of 5.", stage='prepare',
                                detail=str(w.peek('newVideoStep')))
    time.sleep(0.4)


def _next(w, number, timeout=60):
    w.click('newVideoNext')
    _step(w, number, timeout)


def _tick_files(w, srcs):
    """Tick the job's files in the Content step's list (a click on each row, as a person does)."""
    want = {Path(p).name.lower() for p in srcs['files']}
    rows = (w.widget('newVideoMedia') or {}).get('rows') or []
    seen = set()
    for row in rows:
        name = str(row.get('text') or '').strip().lower()
        if name in want and not row.get('selected'):
            w.call('qa_mouse', {'type': 'click', 'x': int(row['x'] + min(40, row['width'] // 3)),
                                'y': int(row['y'] + row['height'] // 2)})
            time.sleep(0.5)
        if name in want:
            seen.add(name)
    missing = want - seen
    if missing:
        raise state.StudioError('source_unreadable', "New video didn't list these files in the footage folder: "
                                + ', '.join(sorted(missing)) + '. Put the footage for one Short in one folder.',
                                stage='prepare')
    said = lambda: str((w.peek('newVideoFound') or {}).get('text') or '')     # noqa: E731
    if not w.wait_for(lambda: f'{len(want)} file' in said() and 'selected' in said(), 15, 0.5):
        raise state.StudioError('internal', f"New video did not take the job's {len(want)} files.", stage='prepare',
                                detail=said())


def start_new_video(ctx, job, job_dir, run, check):
    """The New video dialog, step by step, as the person fills it in; then Make my video. Returns the window."""
    w = _window(ctx, job, job_dir, run, PREVIEW_STOP if tier_of(job) == 'preview' else None)
    try:
        inp = job.get('inputs') or {}
        srcs = run['sources']
        w.call('trigger', {'name': 'makeFirstCutAction'})
        _step(w, 1)
        w.click('newVideoKind_short')
        _next(w, 2)
        check()
        if srcs['mode'] == 'none':
            w.click('newVideoNoFootage')
        else:
            if not (w.peek('newVideoUseFootage') or {}).get('missing'):
                w.click('newVideoUseFootage')
            w.widget('firstCutFolder', 'set', srcs['folder'])
            found = w.wait_for(lambda: re.match(r'[1-9]\d* media files', w.widget('newVideoFound').get('text') or ''),
                               120, 1)
            if not found:
                raise state.StudioError('no_footage_for_idea', 'New video found no footage in '
                                        f"{srcs['folder']}.", stage='prepare')
            time.sleep(3)
            if srcs['mode'] == 'pieces':
                _tick_files(w, srcs)
        _next(w, 3)
        check()
        w.wait_for(lambda: w.widget('newVideoStyleTab_all').get('visible'), 60, 1)
        w.wait_for(lambda: 'Looking at your clips' not in (w.peek('newVideoFilmedNote').get('text') or ''), 120, 1)
        time.sleep(0.6)
        look = inp.get('look_id') or 'auto'
        # the default Look ("Let the AI pick", badged Default) is the card newVideoStyle_none; a named Look's card is
        # under the tab the clips chose, else under All
        name = 'newVideoStyle_none' if look == 'auto' else 'newVideoLook_' + look
        if not w.wait_for(lambda: not w.peek(name).get('missing'), 6, 1):
            w.widget('newVideoStyleTab_all', 'click')
            time.sleep(0.8)
            if not w.wait_for(lambda: not w.peek(name).get('missing'), 25, 1):
                raise state.StudioError('look_unknown', f'The Look "{look}" is not on this letitedit.',
                                        stage='prepare')
        w.click(name)
        w.wait_for(lambda: (w.peek('newVideoFitNote').get('text') or '').strip()
                   not in ('', 'Checking whether your clips fit this Look...'), 120, 2)
        run['fit_note'] = (w.peek('newVideoFitNote') or {}).get('text')
        _next(w, 4)
        theme = inp.get('theme_id')
        if theme and not (w.peek('newVideoTheme_' + theme) or {}).get('missing'):
            w.click('newVideoTheme_' + theme)
        _next(w, 5)
        if (w.peek('newVideoTurbo') or {}).get('checked'):
            w.widget('newVideoTurbo', 'set', False)
        length = length_text(job)
        if length:                                     # the length is on the Go step; the box remembers the last video
            w.widget('newVideoAiLength', 'set', False)
            time.sleep(0.3)
            w.widget('newVideoLength', 'set', length)
            time.sleep(0.3)
        about = about_text(job, srcs, (inp.get('notes_for_final') or None) if tier_of(job) == 'final' else None)
        if run.get('prepared_project'):
            about += ('\nThe Studio has already prepared this project: ' + run['prepared_project'] +
                      '. Use that existing project; do not create another. Keep its stage artifacts beside it.')
        w.widget('firstCutAbout', 'set', about)
        run['about'] = about
        if run.get('prepared_project'):
            write_overlay_boxes(job, run, Path(run['prepared_project']))
        run['go'] = {n: (w.peek(n) or {}).get('text') for n in ('newVideoReadyLook', 'newVideoSummary',
                                                                 'newVideoReadyAi', 'newVideoReadyModel')}
        check()
        _begin_attempt(run)
        _save_run(ctx, run)
        w.click('firstCutGo', 2)
        problem = (w.peek('firstCutProblem') or {})
        if problem.get('visible') and problem.get('text'):
            raise state.StudioError('ai_failed', f"New video did not start: {problem['text']}", stage='prepare')
        folder = w.wait_for(lambda: _project_folder(w.projects, run['since']), 60, 1)
        if not folder:
            raise state.StudioError('ai_failed', 'New video did not start (no folder for the video was made).',
                                    stage='prepare')
        run['folder'] = str(Path(run['prepared_project']).parent) if run.get('prepared_project') else str(folder)
        run['started'] = True
        typed = typed_request_check(job, run, folder)
        if typed is not None:
            run['typed_request'] = typed
        _save_run(ctx, run)
        return w
    except BaseException:
        close_window(job)
        raise


def typed_request_check(job, run, folder):
    """With the typed request switch on (T331 P4, on by default): the record the editor wrote when Go was pressed
    (new-video-request.json), checked two ways. `parity`: its fields render the text the editor sent. `resolver`: the
    windowless resolver (new_video_resolve) makes the same request from this job's choices, so a later runner can make
    it without the dialog. Returns None with the switch off; never fails the job (the request has already gone)."""
    import letitedit.app.new_video_request as nvr
    if not nvr.enabled():
        return None
    from letitedit.studio import new_video_resolve
    record, where = None, None
    for place in dict.fromkeys(str(p) for p in (folder, run.get('folder')) if p):
        try:
            record = nvr.read(place)
        except nvr.RequestError as error:
            return {'path': str(Path(place) / nvr.FILE), 'error': str(error)}
        if record is not None:
            where = Path(place) / nvr.FILE
            break
    if record is None:
        return {'missing': True}
    out = {'path': str(where), 'parity': nvr.parity(record)}
    detected = {'style': (record.get('filmed_style') or {}).get('id'), 'angles': bool(record.get('multicam'))}
    try:
        mine = new_video_resolve.resolve(new_video_resolve.choices_of(
            job, run.get('sources') or {}, run.get('about') or '', length_text(job), record.get('save_folder') or '',
            detected))
        theirs = nvr.render(record)
        made = nvr.render(mine)
        at = None if made == theirs else next((i for i, (a, b) in enumerate(zip(made, theirs)) if a != b),
                                              min(len(made), len(theirs)))
        out['resolver'] = {'ok': at is None, 'first_difference': at}
        if at is not None:
            out['resolver'].update(editor=theirs[max(0, at - 80):at + 120], resolver=made[max(0, at - 80):at + 120])
    except nvr.RequestError as error:
        out['resolver'] = {'ok': False, 'error': str(error)}
    return out


def _notes(folder, since):
    """[(time, stage)] of the stage done notes of the video's working folders since `since`."""
    import letitedit.app.new_video_stages as nvs
    out = []
    for work in Path(folder).glob('*.letitedit'):
        out += nvs.stage_notes(work / 'journal.jsonl', since)
    return sorted(out)


def _ensure_window(ctx, job, job_dir, check):
    """The job's window, started (and New video with it) when this process has none: a first start, or after a stop
    (the earlier attempt's window is ended and the video starts again)."""
    run = _run(ctx)
    w = _WINDOWS.get(job['job_id'])
    if w is not None and w.alive():
        return w, run
    if job.get('from_job'):
        return continue_final(ctx, job, job_dir, run, check), _run(ctx)
    run.pop('folder', None)
    run.pop('started', None)
    return start_new_video(ctx, job, job_dir, run, check), _run(ctx)


def _wait_until(ctx, job, job_dir, check, done, what, stage):
    """Watch the run until done(run) holds: the AI's turn ends and the app carries on as the person's window does.
    A window that dies, or an AI idle for STALLED_S with the stage not done, fails the job (ai_failed)."""
    w, run = _ensure_window(ctx, job, job_dir, check)
    idle_since, last_refresh = None, 0.0
    while True:
        check()
        run = _run(ctx)
        if done(run):
            return w, run
        if not w.alive():
            _WINDOWS.pop(job['job_id'], None)
            raise state.StudioError('ai_failed', f"letitedit's window for this job stopped before {what}.",
                                    stage=stage)
        st = w.chat_state()
        busy = bool(st.get('busy')) or bool(st.get('new_video_carry_pending'))
        if busy:
            idle_since = None
        else:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > STALLED_S:
                said = str(st.get('last_answer') or st.get('status') or '')[:300]
                raise state.StudioError('ai_failed', f'The AI stopped before {what}.' + (f' It said: {said}' if said
                                                                                        else ''),
                                        stage=stage)
        if time.time() - last_refresh > 60:
            w.refresh()
            last_refresh = time.time()
        time.sleep(POLL_S)


def _waiter(stage):
    def wait(ctx, job_dir, job, attempt, check=lambda: None):
        if _run(ctx).get('backend') == BACKEND_RUNNER:
            runner_stage(ctx, job_dir, job, stage, check)
            state.event(job_dir, job, 'progress', stage=stage, message=f'New video: the {stage} stage is done.')
            return None

        def done(run):
            if stage in (run.get('done_before') or ()):         # a final from a preview that already did it
                return True
            return bool(run.get('folder')) and any(s == stage for _, s in _notes(run['folder'], run['since']))
        _wait_until(ctx, job, job_dir, check, done, f'the {stage} stage', stage)
        state.event(job_dir, job, 'progress', stage=stage, message=f'New video: the {stage} stage is done.')
        return None
    wait.__name__ = f'wait_{stage}'
    return wait


def prepare(ctx, job_dir, job, attempt, check=lambda: None):
    home = _home()
    srcs = resolve_sources(job, home)
    check_sources(srcs)
    srcs = sdr_footage(job_dir, srcs, check)
    run = {'sources': srcs, 'tier': tier_of(job)}
    project = prepare_project(job_dir)
    run.update(project=str(project), prepared_project=str(project), folder=str(project.parent))
    if backend(job, job_dir, _run(ctx)) == BACKEND_RUNNER and runner_prepare(ctx, job, job_dir, run, check):
        return None
    run['backend'] = BACKEND_WINDOW
    _save_run(ctx, run)
    start_new_video(ctx, job, job_dir, run, check)
    return None


def prepare_project(job_dir):
    """Make the Studio's empty vertical project before its New video AI can start; never replace a retry's work."""
    from letitedit.timeline import letitedit_extras
    project = Path(job_dir).resolve() / 'work' / 'prepared' / 'Studio short.mlt'
    if not project.exists():
        letitedit_extras.new_project(str(project), width=1080, height=1920, fps=30, claim=False)
    project.with_suffix('.letitedit').mkdir(parents=True, exist_ok=True)
    return project


# ------------------------------------------------------------------ the session runner (T331 P9; on by default)

BACKEND_RUNNER, BACKEND_WINDOW = 'runner', 'window'


def _job_window(job, job_dir):
    """The job's window as an object only (never started here): its folders and the chat settings it would run with
    (the person's, with the job's `ai` applied; written to the job's own window folder, never the person's)."""
    import letitedit.studio.window as window
    return window.StudioWindow(_home(), job, job_dir, _lane(job))


def backend(job, job_dir, run=None):
    """How this job's New video runs: BACKEND_RUNNER (session_runner: on disk, no window) when that switch is on and the
    job's AI is one the runner drives, else BACKEND_WINDOW. Chosen once, before anything starts, and kept in the run:
    a job never changes backend part way, and an uncertain state after a launch stops the job, never re-runs it in a
    window."""
    if run and run.get('backend'):
        return run['backend']
    import letitedit.studio.session_runner as session_runner
    if not session_runner.enabled():
        return BACKEND_WINDOW
    engine = _job_window(job, job_dir)._write_settings().get('engine') or 'claude'
    return BACKEND_RUNNER if session_runner.supported(engine) is None else BACKEND_WINDOW


def runner_request(job, run, project):
    """The New video request the dialog would send for this job, made without it (new_video_resolve over the clips'
    detection, as the dialog's Look step does), kept beside the project as text and typed record. RequestError when
    it can't be made without a person."""
    import letitedit.app.new_video_request as nvr
    import letitedit.app.what_was_filmed as what_was_filmed
    from letitedit.studio import new_video_resolve
    inp = job.get('inputs') or {}
    srcs = run['sources']
    about = about_text(job, srcs, (inp.get('notes_for_final') or None) if tier_of(job) == 'final' else None)
    about += ('\nThe Studio has already prepared this project: ' + str(project) +
              '. Use that existing project; do not create another. Keep its stage artifacts beside it.')
    import letitedit.app.letitedit_instances as instances
    import letitedit.studio.window as window
    detected = None
    if srcs['mode'] != 'none':
        detected = what_was_filmed.detect(srcs['files'] or [srcs['folder']])
    # resolved as the job's own instance (the one its runner's tool server works as, and its window would be): the
    # Looks "Let the AI pick" offers are that instance's, never the person's own My Looks, which the job's AI can't
    # read (T331 P12: the Studio's worker runs as 'main', so its list had the person's private Looks in it)
    with instances.scope(window.instance_for(job['job_id'])):
        record = new_video_resolve.resolve(new_video_resolve.choices_of(job, srcs, about, length_text(job),
                                                                        str(project.parent), detected))
    text = nvr.render(record)
    work = project.with_suffix('.letitedit')
    work.mkdir(parents=True, exist_ok=True)
    nvr.write(work, record, text, origin='studio-runner')
    (work / REQUEST_FILE).write_text(text, encoding='utf-8')
    files.write_json(work / SOURCES_FILE, srcs)
    run.update(about=about, request=text, look_id=record.get('look_id') or inp.get('look_id') or 'auto')
    write_overlay_boxes(job, run, project)
    return text


# What the job's window gives its AI and tool server that a run without the window needs too (T331 P12): the job's own
# chat settings (the job's `ai` applied: the critic and every other tool that reads the chat's choice read them, never
# the person's panel.json), its progress and learning folders, Look sharing off, and its lane in the PC lock's line.
RUNNER_WINDOW_ENV = ('LETITEDIT_CHAT_SETTINGS', 'LETITEDIT_PROGRESS_DIR', 'LETITEDIT_LEARN_JOBS',
                     'LETITEDIT_SHARE_URL', 'LETITEDIT_SHARING_DIR', 'LETITEDIT_LOCK_PRIORITY')


def _runner_for(ctx, job, job_dir, run, check):
    import letitedit.studio.session_runner as session_runner
    import letitedit.studio.window as window
    w = _job_window(job, job_dir)
    settings = w._write_settings()
    project = Path(run['project'])
    request = (project.with_suffix('.letitedit') / REQUEST_FILE).read_text(encoding='utf-8')
    w.work_dir.mkdir(parents=True, exist_ok=True)
    window_env = w.env()
    env = {k: window_env[k] for k in RUNNER_WINDOW_ENV if window_env.get(k)}
    env.update({'LETITEDIT_PROJECTS_FOLDER': str(Path(job_dir) / 'work'), 'LETITEDIT_INSTANCE': w.instance,
                'LETITEDIT_JOBS': window.tool_jobs_root()})
    return session_runner.Runner(
        project, request, engine=settings.get('engine') or 'claude', settings=settings, work_dir=w.work_dir,
        stop_after=PREVIEW_STOP if tier_of(job) == 'preview' else None,
        start_phase='fine_finish' if job.get('from_job') else None, check=check,
        note=lambda text: state.event(job_dir, job, 'progress', message=text), env=env)


def runner_prepare(ctx, job, job_dir, run, check):
    """The runner's prepare: the request made without the dialog and the runner's own checks, before anything starts.
    Returns False (the window path then runs, with an event saying why) when either can't be done; nothing has been
    launched yet, so that is the only fallback there is."""
    import letitedit.app.new_video_request as nvr
    import letitedit.studio.session_runner as session_runner
    project = Path(run['project'])
    try:
        if job.get('from_job'):
            text, _ = final_request(job, run)
            (project.with_suffix('.letitedit') / REQUEST_FILE).write_text(text, encoding='utf-8')
            run['request'] = text
        else:
            runner_request(job, run, project)
        _runner_for(ctx, job, job_dir, run, check).preflight()
    except (nvr.RequestError, session_runner.RunnerError) as e:
        state.event(job_dir, job, 'progress', stage='prepare',
                    message=f'New video runs in its window: {getattr(e, "message", None) or e}')
        return False
    run['backend'] = BACKEND_RUNNER
    _begin_attempt(run)
    run['started'] = True
    _save_run(ctx, run)
    state.event(job_dir, job, 'progress', stage='prepare', message='New video runs on disk, with no window.')
    return True


RUNNER_CODES = {'usage_limit': 'ai_limit', 'signin': 'ai_unavailable', 'ai_missing': 'ai_unavailable'}


def runner_stage(ctx, job_dir, job, stage, check=lambda: None):
    """A New video stage on the runner: its phase runs to its end (a later stage of the same phase finds it done)."""
    import letitedit.app.phases as phases
    import letitedit.studio.session_runner as session_runner
    run = _run(ctx)
    if stage in (run.get('done_before') or ()):
        return
    phase = phases.phase_of(stage)
    if job.get('from_job') and phase == 'plan_rough':
        return
    try:
        _runner_for(ctx, job, job_dir, run, check).run_until(phase)
    except session_runner.RunnerError as e:
        code = RUNNER_CODES.get(e.code, 'ai_failed')
        raise state.StudioError(code, e.message, stage=stage, detail=f'{e.kind}:{e.code}') from e


# ------------------------------------------------------------------ the preview's end

def _project_of(folder):
    """The video's project (.mlt) in its folder: the one with a working folder beside it, newest first."""
    best = None
    for work in Path(folder).glob('*.letitedit'):
        mlt = work.parent / (work.name[:-len('.letitedit')] + '.mlt')
        if mlt.is_file() and (best is None or mlt.stat().st_mtime > best.stat().st_mtime):
            best = mlt
    return best


def _request_of(w):
    """The New video request the window sent (the chat keeps it with the conversation)."""
    hist = w.chat_settings.parent / 'history.json'
    try:
        data = json.loads(hist.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return ''
    chats = data if isinstance(data, list) else data.get('chats') or data.get('records') or []
    if isinstance(chats, dict):
        chats = list(chats.values())
    for c in reversed(chats if isinstance(chats, list) else []):
        if isinstance(c, dict) and c.get('new_video_request'):
            return c['new_video_request']
    return ''


def _keep_request(w, run, project):
    text = _request_of(w) or run.get('request') or ''
    if text and project:
        work = project.with_suffix('.letitedit')
        work.mkdir(exist_ok=True)
        (work / REQUEST_FILE).write_text(text, encoding='utf-8')
    if project and run.get('sources'):
        files.write_json(project.with_suffix('.letitedit') / SOURCES_FILE, run['sources'])
    typed = Path(str((run.get('typed_request') or {}).get('path') or ''))
    if project and typed.name and typed.is_file():               # T331 P4: the typed request, kept with the text
        work = project.with_suffix('.letitedit')
        if typed.parent.resolve() != work.resolve():
            shutil.copyfile(typed, work / typed.name)
    return text


def preview_result(ctx, job_dir, job, attempt, check=lambda: None):
    """The AI's turn ended after the rough cut: the window closed; the rough cut exported; the phone proxy and its
    poster, with draft captions from the timeline's words; the shared fields that can be said at this point."""
    run = _run(ctx)
    w = _WINDOWS.get(job['job_id'])
    if w is not None:
        end = time.time() + STOP_WAIT_S
        quiet = None
        while time.time() < end:                         # the hand-over is written, then the turn ends
            check()
            st = w.chat_state()
            if not st.get('busy') and not st.get('new_video_carry_pending'):
                quiet = quiet or time.time()
                if time.time() - quiet > 8:
                    break
            else:
                quiet = None
            time.sleep(POLL_S)
        save_window(job, job_dir, 'proxy', _project_of(run['folder']))
        project = _project_of(run['folder'])
        run['request'] = _keep_request(w, run, project)
        _save_run(ctx, run)
        close_window(job)
    project = _project_of(run['folder'])
    if project is None:
        raise state.StudioError('ai_failed', 'The rough cut was made but its project could not be found.',
                                stage='proxy')
    master = _export_project(project, Path(ctx.dir) / 'rough.mp4', check)
    parts = read_project(job, job_dir, project, master, run.get('sources'))
    # Only a caption feed's cues are drawn on the proxy: word-pop captions are already in its picture.
    captions = caption_cues(parts['script'].get('captions'))
    draft = not parts['captions']
    if draft:
        captions = draft_captions(project)
        draft_words_per_min(parts, captions)
    shared = shared_fields(job, job_dir, project, parts, master, files_made=[], preview=True, since=run['since'])
    proxy, outs = make_proxy(job, job_dir, master, shared, captions=captions, project=project)
    shared['proxy'] = proxy
    output = {'files': [], 'project': _rel(job_dir, project), 'summary': _summary(job, parts, preview=True),
              'left_out': parts.get('left_out') or []}
    if draft and captions:
        shared.setdefault('notes', []).append('The proxy has draft captions from the timeline\'s own words; the '
                                              "final's captions are made in its finish stage.")
    return _result(ctx, job, job_dir, output, shared, outs, project)


def _export_project(project, out, check, chunk_s=None):
    """letitedit's own export of the project (the export worker, under the PC lock, at -14 LUFS / -1 dBTP). The
    export's id is saved beside `out` before waiting, so a job started again after a stop takes up that same export
    instead of starting another. A cancel stays a cancel: the export is cancelled too, and waited for."""
    import letitedit.timeline.render_queue as rq
    check()
    out = Path(out)
    note = out.with_name(out.name + '.export.json')
    jid = (files.read_json(note) or {}).get('job_id')
    try:
        st = rq.status(jid) if jid else {}
        if st.get('state') == 'interrupted':           # its worker stopped with the PC: carry on with its chunks
            st = rq.resume(jid)
    except (KeyError, OSError):
        jid, st = None, {}
    if not jid or st.get('state') in (None, 'failed', 'interrupted', 'cancelled', 'error')             or (st.get('state') == 'done' and not out.is_file()):
        out.unlink(missing_ok=True)
        try:
            job = rq.submit(str(project), output=str(out), loudness=-14.0, overwrite=True, true_peak=-1.0,
                            **({'chunk_s': chunk_s} if chunk_s is not None else {}))
        except Exception as e:  # noqa: BLE001 - its message says what went wrong
            raise state.StudioError('render_failed', 'letitedit could not export the video.', detail=str(e)[:1500])
        jid = job.get('job_id') or job.get('id')
        files.write_json(note, {'job_id': jid, 'output': str(out)})
        st = {}
    try:
        while st.get('state') not in ('done', 'failed', 'interrupted', 'cancelled', 'error'):
            check()
            time.sleep(5)
            st = rq.status(jid)
    except BaseException:
        _stop_export(rq, jid)
        raise
    if st.get('state') != 'done':
        raise state.StudioError('render_failed', 'letitedit could not export the video.',
                                detail=json.dumps(st, default=str)[:1500])
    if not out.is_file() or out.stat().st_size == 0:
        raise state.StudioError('render_failed', 'letitedit could not export the video.', detail=str(out))
    return out


def _stop_export(rq, jid, wait_s=120):
    """Cancel an export this job started and wait (up to wait_s) until its worker has stopped it."""
    try:
        rq.cancel(jid)
        end = time.time() + wait_s
        while time.time() < end:
            if rq.status(jid).get('state') in ('done', 'failed', 'interrupted', 'cancelled', 'error'):
                return
            time.sleep(1)
    except Exception:  # noqa: BLE001 - the cancel itself is best effort; the job's own cancel goes on
        pass


def caption_cues(feeds):
    """[(start, end, text)] of the captions the video shows, from the timeline's caption feeds. A project may hold
    more than one feed of the same words (the captions drawn on the picture, in short chunks, and full sentences kept
    for upload), so one is chosen: the feeds a burn draws when the reading says so, else the feed with the most cues
    (the chunked one a Short shows). Never two feeds' cues side by side, which would repeat every line."""
    feeds = [f for f in feeds or [] if f.get('cues')]
    if not feeds:
        return []
    burned = [f for f in feeds if f.get('burn_in') is not False]
    chosen = burned or [max(feeds, key=lambda f: len(f['cues']))]
    out = []
    for f in chosen:
        for cue in f['cues']:
            text = ' '.join(str(cue.get('text') or '').split())
            if text:
                out.append((_secs(cue.get('start')), _secs(cue.get('end')), text))
    return sorted(set(out))


def draft_words_per_min(parts, captions):
    """A rough cut has no caption feed, so its words per minute come from the draft captions (the words heard on the
    timeline); choices.words_per_min is required. Left as it is when the timeline gave a count or no words."""
    if parts.get('words_per_min') is None and captions:
        words_n = sum(len(t.split()) for _, _, t in captions)
        parts['words_per_min'] = round(words_n / (max(parts.get('duration_s') or 0.0, 1.0) / 60.0), 1)
    return parts


def draft_captions(project, max_words=6, max_s=2.6):
    """[(start, end, text)] from the words heard on the timeline, in short chunks: a preview's draft captions."""
    try:
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.timeline_speech as timeline_speech
        words = timeline_speech.timeline_words(es.read(str(project)), None, None) or []
    except Exception:  # noqa: BLE001 - a proxy without captions is still a proxy
        return []
    return caption_chunks(words, max_words, max_s)


def caption_chunks(words, max_words=6, max_s=2.6):
    """Timeline words ({w, t0, t1}; {w, s, e} taken too) in short chunks [(start, end, text)]; a word with no length
    is left out (a caption with no time on screen would never show)."""
    out, cur = [], []
    for w in words:
        s = float(w.get('t0', w.get('s', 0)) or 0)
        e = float(w.get('t1', w.get('e', 0)) or 0)
        t = str(w.get('w', '')).strip()
        if not t or e <= s:
            continue
        if cur and (len(cur) >= max_words or e - cur[0][0] > max_s or s - cur[-1][1] > 0.6):
            out.append((cur[0][0], cur[-1][1], ' '.join(x[2] for x in cur)))
            cur = []
        cur.append((s, e, t))
    if cur:
        out.append((cur[0][0], cur[-1][1], ' '.join(x[2] for x in cur)))
    return out


# ------------------------------------------------------------------ a final from a preview

def _rewrite(folder, old, new):
    """Every text file of a copied project names the new folder where it named the old one (both slash forms, and as
    XML writes them)."""
    pairs = []
    for o, n in ((str(old), str(new)), (str(old).replace('\\', '/'), str(new).replace('\\', '/'))):
        pairs += [(o, n), (o.replace('&', '&amp;'), n.replace('&', '&amp;'))]
    for p in Path(folder).rglob('*'):
        if not p.is_file() or p.suffix.lower() not in ('.mlt', '.json', '.jsonl', '.md', '.txt', '.yaml', '.srt',
                                                        '.bak') or p.stat().st_size > 50_000_000:
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        changed = text
        for o, n in pairs:
            changed = changed.replace(o, n)
            if '\\' in o:
                changed = changed.replace(o.replace('\\', '\\\\'), n.replace('\\', '\\\\'))
        if changed != text:
            p.write_text(changed, encoding='utf-8', newline='')


def _earlier(job, home):
    import letitedit.studio.service as service
    folder = service.find(home, job['from_job'])
    r = files.read_json(folder / 'result.json') if folder else None
    if not r or r.get('state') != 'done' or r.get('kind') != 'short':
        raise state.StudioError('from_job_unusable', f"The earlier job {job['from_job']} isn't a finished Short.",
                                stage='prepare')
    return folder, r


def prepare_from(ctx, job_dir, job, attempt, check=lambda: None):
    """The preview's project copied into this job's folder (the preview stays as it was), its paths rewritten; then
    New video goes on from the rough cut (continue_final)."""
    home = _home()
    earlier_run = _run(ctx)
    before_dir, before = _earlier(job, home)
    project = before_dir / ((before.get('output') or {}).get('project') or '')
    if not project.is_file():
        raise state.StudioError('from_job_unusable', "The preview's project is not in its job folder any more.",
                                stage='prepare')
    old = project.parent
    new = Path(job_dir) / 'work' / old.name
    if new.exists():
        shutil.rmtree(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    # Every file the project uses comes along (made scenes, cutaways, fitted media); only the preview's own recorded
    # exports stay behind, matched by path. An earlier copy cut short is removed above and made again whole.
    recorded = {os.path.normcase(os.path.abspath(old / e['output'])) for e in _exports(old) if e.get('output')}
    import letitedit.app.work_in_passes as work_in_passes      # T353, behind its own switch (on by default)
    if work_in_passes.enabled():
        # the renders the journal records as watched (`render:<path>`, the rough stage's watched export) come along,
        # so the rough stage still checks out in this folder once the paths are rewritten
        recorded -= {os.path.normcase(os.path.abspath(path)) for path in
                     work_in_passes.watched_renders(project.with_suffix('.letitedit'))}

    def leave_out(d, names):
        return {n for n in names if n in ('lease.json', 'hooks.json.lock')
                or os.path.normcase(os.path.abspath(os.path.join(d, n))) in recorded}
    shutil.copytree(old, new, ignore=leave_out)
    _rewrite(new, old, new)
    earlier_job = files.read_json(before_dir / 'job.json') or {}
    kept = files.read_json((new / project.name).with_suffix('.letitedit') / SOURCES_FILE)
    run = {'tier': 'final', 'from': str(before_dir), 'folder': str(new), 'project': str(new / project.name),
           'look_id': (before.get('choices') or {}).get('look_id'), 'earlier_job': earlier_job,
           'sources': kept or resolve_sources(earlier_job, home)}
    if backend(job, job_dir, earlier_run) == BACKEND_RUNNER and runner_prepare(ctx, job, job_dir, run, check):
        return None
    run['backend'] = BACKEND_WINDOW
    _save_run(ctx, run)
    continue_final(ctx, job, job_dir, run, check)
    return None


def done_before(folder):
    """The New video stages the video's journal already marks done (its preview's, or an earlier attempt's), in stage
    order. A preview stops after the rough cut, but its AI can go on further (T305: its preview reached the fine
    cut); those stages are done and the final goes on after them."""
    seen = {s for _, s in _notes(folder, 0)}
    return [s for s in STAGE_ORDER if s in seen]


def next_stage(done):
    """The stage a final from a preview carries on with: the one after the last done stage (fine after the rough cut,
    as before; finish after the fine cut; the review after finish)."""
    import letitedit.app.new_video_stages as nvs
    last = next((s for s in reversed(STAGE_ORDER) if s in done), PREVIEW_STOP)
    return nvs.NEXT.get(last, nvs.NEXT[PREVIEW_STOP])


def final_request(job, run):
    """(request, handover): the preview's New video request for this final (its save folder moved to this job's copy,
    the person's notes and rules for the final and the closing asks added), and its hand-over note (written when the
    preview left none). The window's continue_final and the session runner both send it."""
    folder = Path(run['folder'])
    project = Path(run['project'])
    work = project.with_suffix('.letitedit')
    request = (work / REQUEST_FILE).read_text(encoding='utf-8') if (work / REQUEST_FILE).is_file() else ''
    if not request:
        raise state.StudioError('from_job_unusable', "The preview's New video request was not kept, so the final "
                                'cannot carry on from it. Make a new preview.', stage='prepare')
    old_folder = re.search(r'Save video in: (.+)', request)
    if old_folder:
        request = request.replace(old_folder.group(1).strip(), str(folder).replace('\\', '/'))
    handover = work / 'handover.md'
    if not handover.is_file() or not handover.read_text(encoding='utf-8').strip():
        handover.write_text('The preview stopped after the rough cut, which is done and saved in the project. Carry '
                            'on with the fine cut.\n', encoding='utf-8')
    run['done_before'] = done_before(folder)
    write_overlay_boxes(job, run, project)
    inp = job.get('inputs') or {}
    extra = []
    if _notes_list(inp.get('notes_for_final')):
        extra.append("The person's notes on the preview, for this final: "
                     + ' '.join(_said(n) for n in _notes_list(inp['notes_for_final'])))
    if inp.get('rules') is not None:
        extra.append(final_rules_text(inp['rules']))
    srcs = run.get('sources') or {'ranges': [], 'strict': False, 'mode': 'none'}
    tail = about_text({**run.get('earlier_job', {}), 'inputs': {**(run.get('earlier_job') or {}).get('inputs', {}),
                                                               **{k: inp[k] for k in ('rules', 'deliver') if k in inp}}},
                      {**srcs, 'ranges': []}).splitlines()
    asks = [ln for ln in tail if ln.startswith(('When the review is done', 'At the end add a journal note'))]
    request += '\n' + '\n'.join(extra + asks) if extra or asks else ''
    return request, handover


def continue_final(ctx, job, job_dir, run, check):
    """New video goes on from the hand-over in a fresh conversation with the app's own next-stage message, sent the
    way the app sends a New video that waited for its Look (a pending-video.json with the video's folder)."""
    import letitedit.app.new_video_stages as nvs
    folder = Path(run['folder'])
    project = Path(run['project'])
    request, handover = final_request(job, run)
    w = _window(ctx, job, job_dir, run)
    try:
        w.call('open', {'path': str(project)})
        w.wait_for(lambda: not (w.call('state', timeout=5) or {}).get('opening'), 60, 1)
        startup = nvs.start_request(request, next_stage(run['done_before']), project, handover=handover,
                                    ai=w.settings().get('engine') or 'claude')
        text = startup['request']
        learn = w.base / 'learning' / 'studio-final'
        learn.mkdir(parents=True, exist_ok=True)
        files.write_json(learn / 'job.json', {'state': 'done', 'look_id': run.get('look_id') or 'auto',
                                              'name': run.get('look_id') or 'auto', 'pid': 0})
        _begin_attempt(run)
        run['request'] = text
        _save_run(ctx, run)
        files.write_json(learn / 'pending-video.json', {'request': text, 'folder': str(folder),
                                                        'startup': {key: value for key, value in startup.items()
                                                                    if key != 'request'},
                                                        'summary': 'Finish my video from its preview'})
        sent = w.wait_for(lambda: not (learn / 'pending-video.json').exists(), 60, 1)
        if not sent:
            raise state.StudioError('ai_failed', 'The AI did not take the final (letitedit could not send it).',
                                    stage='prepare')
        run['started'] = True
        _save_run(ctx, run)
        return w
    except BaseException:
        close_window(job)
        raise


# ------------------------------------------------------------------ the final's end

def _exports(folder):
    out = []
    for work in Path(folder).glob('*.letitedit'):
        data = files.read_json(work / 'exports.json') or {}
        out += [e for e in data.get('exports') or [] if isinstance(e, dict)]
    return out


def final_export(folder, since):
    """The AI's last full export of this run (not a preview render), or None."""
    best = None
    for e in _exports(folder):
        p = Path(e.get('output') or '')
        if e.get('preview') or not p.is_file() or p.stat().st_mtime < since:
            continue
        if best is None or p.stat().st_mtime > best.stat().st_mtime:
            best = p
    return best


def _review_bundle(folder, since):
    best = None
    for b in list(Path(folder).glob('* review/review_bundle.json')) + list(Path(folder).glob('*/* review/review_bundle.json')):
        if b.stat().st_mtime >= since and (best is None or b.stat().st_mtime > best.stat().st_mtime):
            best = b
    return best


def _review_finished(bundle):
    """Whether a review bundle is a finished review: review_bundle.py writes a partial review_bundle.json before its
    critic runs, and the whole one followed by review.md when the review ends."""
    try:
        return (bundle.parent / 'review.md').stat().st_mtime_ns >= bundle.stat().st_mtime_ns
    except OSError:
        return False


def _same_file(a, b):
    try:
        return bool(a) and bool(b) and os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except (OSError, ValueError):
        return False


def _review_covers(bundle, export):
    """Whether the review is of the final export: it names it (the video it reviewed, or the final export it started
    on a preview), or it was finished after that export was written."""
    data = files.read_json(bundle) or {}
    video = data.get('video')
    video = video.get('file') if isinstance(video, dict) else video
    started = data.get('final_export') if isinstance(data.get('final_export'), dict) else {}
    if _same_file(video, export) or _same_file(started.get('output'), export):
        return True
    try:
        return bundle.stat().st_mtime >= export.stat().st_mtime
    except OSError:
        return False


EXPORT_ENDED = ('done', 'failed', 'cancelled', 'interrupted')
EXPORT_WORKING = ('rendering', 'waiting', 'waiting_space', 'joining', 'audio', 'checking')   # a worker runs it


def exports_running(folder, since=0.0):
    """The export jobs writing into the video's folder that haven't ended, read from each job's status as
    render_queue.status reads it (a worker that has died is interrupted). A job with no status yet, or queued, counts
    while it was submitted in this run (since `since`): it is about to start; an older queued one never started."""
    import letitedit.core.render_lock as render_lock
    import letitedit.timeline.render_queue as rq
    root, out = Path(folder).resolve(), []
    for spec_path in Path(rq.JOBS).glob('*/spec.json'):
        spec = files.read_json(spec_path) or {}
        try:
            if not spec.get('output') or not Path(spec['output']).resolve().is_relative_to(root):
                continue
            st = files.read_json(spec_path.parent / 'status.json') or {}
            state_now = st.get('state') or 'queued'
            if state_now in EXPORT_ENDED:
                continue
            if state_now in EXPORT_WORKING and not render_lock.pid_alive(st.get('pid')):
                continue                                     # interrupted
            if state_now not in EXPORT_WORKING and spec_path.stat().st_mtime < since:
                continue                                     # queued before this run and never started
            out.append(spec_path.parent.name)
        except (OSError, ValueError):
            continue
    return out


def final_receipts(folder, since):
    """(True, '') when the run's final receipts are all written: the final export on disk with no export job of the
    video's folder still running, and a finished review of that export; else (False, what is missing)."""
    if exports_running(folder, since):
        return False, 'an export is still running'
    export = final_export(folder, since)
    if export is None:
        return False, 'no final export yet'
    bundle = _review_bundle(folder, since)
    if bundle is None:
        return False, 'no review yet'
    if not _review_finished(bundle):
        return False, 'the review is still running'
    if not _review_covers(bundle, export):
        return False, 'the final export is newer than its review'
    return True, ''


def session_ended(st):
    """True when the window says New video's AI session has ended: not busy, no carry-on pending or review
    conversation, and its request closed (the editor keeps the request open while it carries the run on, and closes it
    when the run is finished, blocked or stopped). None when the window's state doesn't say (unreadable, or a build
    without these fields)."""
    if not isinstance(st, dict) or any(key not in st for key in ('busy', 'new_video_carry_pending', 'request')):
        return None
    return not (st.get('busy') or st.get('new_video_carry_pending') or st.get('request')
                or st.get('review_conversation') or st.get('waiting'))


def _receipts_mark(folder, since):
    """What the receipts are now (the final export and the review, with their dates): a change restarts the waits."""
    out = []
    for path in (final_export(folder, since), _review_bundle(folder, since)):
        try:
            out.append((str(path), path.stat().st_mtime_ns) if path else None)
        except OSError:
            out.append((str(path), None))
    return tuple(out)


def end_wait(st, receipts_ok):
    """How long the run must stay as it is before the final counts as done (see wait_review)."""
    ended = session_ended(st)
    if ended and receipts_ok:
        return END_CONFIRM_S
    if ended is None or not receipts_ok:
        return UNSURE_DONE_S
    return IDLE_DONE_S


def wait_review(ctx, job_dir, job, attempt, check=lambda: None):
    """The review rounds, their fixes and the final export: done when the AI's turn has ended with a final export and
    a review, and the app has stopped carrying on. With the end signal (final_receipts, and session_ended from the
    window) that holds for END_CONFIRM_S; without it, after a quiet wait: IDLE_DONE_S when the receipts are complete
    and the window answers, UNSURE_DONE_S otherwise. Never while an export of the video's folder is still running."""
    if _run(ctx).get('backend') == BACKEND_RUNNER:
        runner_stage(ctx, job_dir, job, 'review', check)
        run = _run(ctx)
        receipts_ok, why = final_receipts(run['folder'], run['since'])
        if not receipts_ok:
            raise state.StudioError('ai_failed', f'The review phase ended without its receipts: {why}.',
                                    stage='review')
        state.event(job_dir, job, 'progress', stage='review', message='New video: reviewed and exported.')
        return None
    quiet = {'since': None, 'mark': None}

    def done(run):
        w = _WINDOWS.get(job['job_id'])
        if not run.get('folder') or not final_export(run['folder'], run['since']) \
                or not _review_bundle(run['folder'], run['since']):
            quiet['since'] = None
            return False
        st = w.chat_state() if w else {}
        if st.get('busy') or st.get('new_video_carry_pending') or st.get('review_conversation'):
            quiet['since'] = None
            return False
        receipts_ok, why = final_receipts(run['folder'], run['since'])
        if why == 'an export is still running':
            quiet['since'] = None
            return False
        mark = _receipts_mark(run['folder'], run['since'])
        if mark != quiet['mark']:
            quiet['since'], quiet['mark'] = None, mark
        quiet['since'] = quiet['since'] or time.time()
        return time.time() - quiet['since'] >= end_wait(st, receipts_ok)
    w, run = _wait_until(ctx, job, job_dir, check, done, 'the review', 'review')
    save_window(job, job_dir, 'review', _project_of(run['folder']))
    project = _project_of(run['folder'])
    run['request'] = run.get('request') or _keep_request(w, run, project)
    _save_run(ctx, run)
    close_window(job)
    state.event(job_dir, job, 'progress', stage='review', message='New video: reviewed and exported.')
    return None


def export_files(ctx, job_dir, job, attempt, check=lambda: None):
    """Each platform's file from the AI's final export: the shape checked, under its size cap, its overlay items
    applied, cleaned of location, checked SDR (delivery.py). Saved in the run for the last stage."""
    import letitedit.studio.capabilities as capabilities
    import letitedit.studio.media_privacy as media_privacy
    import letitedit.studio.overlays as overlays
    run = _run(ctx)
    master = final_export(run['folder'], run['since'])
    if master is None:
        raise state.StudioError('ai_failed', 'The AI ended without exporting the video.', stage='export')
    presets = {p['id']: p for p in capabilities.platforms_list()}
    info = delivery.probe(master) or {}
    plats = _platforms(job, run)
    given = None
    if job.get('from_job'):
        r = files.read_json(Path(run['from']) / 'result.json') or {}
        given = overlays.carried(r.get('text_items'))
    provisional = {'output': {'files': [{'platform': p['id'], 'status': 'made'} for p in plats]},
                   'provenance': {'assets': []}, 'music': {'tracks': []}}
    project = _project_of(run['folder'])
    parts = read_project(job, job_dir, project, master, run.get('sources'))
    provisional.update(provenance=parts['provenance'], music=parts['music'])
    decided = overlays.decide(_overlay_job(job, run), provisional, duration_s=info.get('duration_s'), given=given)
    made, outs = [], []
    for p in plats:
        check()
        preset = presets.get(p['id']) or {}
        width, height = int(preset.get('width') or 1080), int(preset.get('height') or 1920)
        if (width > height) != ((info.get('width') or 0) > (info.get('height') or 0)):
            made.append({'platform': p['id'], 'status': 'refused', 'reason': 'shape_differs',
                         'message': f"{preset.get('name', p['id'])} is {width}x{height}; this Short is "
                                    f"{info.get('width')}x{info.get('height')}."})
            continue
        longest = preset.get('max_seconds')
        if longest and (info.get('duration_s') or 0) > float(longest) + 0.05:
            made.append({'platform': p['id'], 'status': 'refused', 'reason': 'too_long_for_platform',
                         'message': f"{preset.get('name', p['id'])} takes videos up to {longest:g} s; this one is "
                                    f"{info.get('duration_s'):.1f} s."})
            continue
        cap = int(p['max_mb'] * 1_000_000) if p.get('max_mb') else preset.get('max_bytes')
        items = _placed(decided, p['id'], width, height, _faces(master), _caption_zone(project))
        run.setdefault('overlay_boxes', {})[p['id']] = {i[0]['overlay'].get('from'): {**(i[2] or {}), 'placed': i[3],
                                                                                      'note': i[4]} for i in items}
        dst = Path(job_dir) / 'files' / f"{p['id']}.mp4"
        got = delivery.fit_under(master, dst, width, height, preset.get('fps') or 30, cap,
                                 [i[1] for i in items if i[2]],
                                 what=f"the {preset.get('name', p['id'])} file")
        if got['status'] != 'made':
            made.append({'platform': p['id'], 'status': 'refused', 'reason': got['reason'], 'message': got['why']})
            continue
        media_privacy.ensure_clean(dst)
        delivery.check_sdr(dst)
        entry = {'platform': p['id'], 'status': 'made', 'video': _rel(job_dir, dst)}
        if got.get('tonemapped') or parts['tonemapped']:
            entry['tonemapped'] = True
        made.append(entry)
        outs.append(files.output_entry(job_dir, entry['video'], 'video', location_metadata='none',
                                       **delivery.describe(dst, p['id'])))
    deliver = (job.get('inputs') or {}).get('deliver') or (run.get('earlier_job', {}).get('inputs') or {}).get('deliver') or {}
    srt = cover = None
    if deliver.get('srt', True) and parts['captions']:
        srt = Path(job_dir) / 'files' / 'captions.srt'
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_text(_srt(parts['captions']), encoding='utf-8')
        outs.append(files.output_entry(job_dir, _rel(job_dir, srt), 'srt'))
    if deliver.get('cover', True):
        cover = Path(job_dir) / 'files' / 'cover.jpg'
        delivery.frame(master, min(0.5, (info.get('duration_s') or 1) / 2), cover, width=1080)
        media_privacy.ensure_clean(cover)
        outs.append(files.output_entry(job_dir, _rel(job_dir, cover), 'cover', location_metadata='none'))
    for m in made:
        if m['status'] == 'made':
            if srt:
                m['srt'] = _rel(job_dir, srt)
            if cover:
                m['cover'] = _rel(job_dir, cover)
    run['made'], run['outs'], run['master'] = made, outs, str(master)
    delivered_overlay_check(job_dir, job, run, project, master, decided, plats)
    _save_run(ctx, run)
    return None


def delivered_overlay_check(job_dir, job, run, project, master, decided, plats):
    """T352, with its switch on: each delivered file's overlay boxes, as drawn, against the video's own text and
    graphics under them (overlay_clash.measure on the export the files are made from). Kept in the run
    (run['overlay_clash']) and beside the project, said in a progress event when a box lies over them."""
    if not overlay_facts_on() or not project or not run.get('overlay_boxes'):
        return None
    import letitedit.review.overlay_clash as overlay_clash
    texts = {t['overlay'].get('from'): t for t in decided}
    items = []
    for p in plats:
        for frm, box in (run['overlay_boxes'].get(p['id']) or {}).items():
            if box.get('x') is None:
                continue
            t = texts.get(frm) or {}
            items.append({'text': t.get('text', ''), 'from': frm, 'placement': box.get('placed'),
                          'platform': p['id'], 'box': {k: box[k] for k in ('x', 'y', 'w', 'h')}})
    if not items:
        return None
    try:
        got = overlay_clash.measure(project, master, items)
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        run['overlay_clash'] = {'error': f'{type(e).__name__}: {e}'[:300]}
        return None
    run['overlay_clash'] = {'items': items, **got}
    overlay_clash.write_boxes(project, items, note="as drawn on each platform's file")
    over = overlay_clash.plain_overlaps(items, got)       # the line, the platform, roughly where, when: no numbers
    if over:
        state.event(job_dir, job, 'progress', stage='export',
                    message="The overlay words lie over the video's own text or graphics: " + '; '.join(over) + '.')
    return got


def _overlay_job(job, run):
    """The job overlays are decided for: its own, with the earlier job's platforms when it names none."""
    inp = dict(job.get('inputs') or {})
    if not inp.get('platforms') and run.get('earlier_job'):
        inp['platforms'] = (run['earlier_job'].get('inputs') or {}).get('platforms') or []
    return {**job, 'inputs': inp}


def _platforms(job, run):
    raw = (job.get('inputs') or {}).get('platforms') or (run.get('earlier_job', {}).get('inputs') or {}).get('platforms') \
        or ['youtube_shorts']
    return [p if isinstance(p, dict) else {'id': p} for p in raw]


def _placed(decided, platform, width, height, faces=(), zone=None, proxy=False):
    """[(text item, (text, x, y, size), box, placement used, note)] of the overlay items applied to this file, in
    one layout (delivery.overlay_layout): stacked, clear of faces, in the Look's caption zone when asked; note says
    what had to give way."""
    chosen = []
    for t in decided:
        files_ = t['overlay']['files']
        entry = next((f for f in files_ if (proxy and f.get('proxy')) or f.get('platform') == platform), None)
        if entry and entry.get('applied'):
            chosen.append(t)
    laid = delivery.overlay_layout([(t['text'], t['overlay'].get('placement') or 'safe_area') for t in chosen],
                                   platform, width, height, faces=faces, zone=zone)
    return [(t, (t['text'], x, y, size) if box else None, box, used, note)
            for t, (x, y, size, box, used, note) in zip(chosen, laid)]


_FACES = {}


def _faces(master, samples=5):
    """The faces seen in the video (moment_facets.face_boxes at a few times through it), once per file."""
    key = str(master)
    if key not in _FACES:
        import letitedit.studio.moment_facets as moment_facets
        d = float((delivery.probe(master) or {}).get('duration_s') or 0)
        times = [d * (k + 0.5) / samples for k in range(samples)] if d else [0.0]
        try:
            _FACES[key] = moment_facets.face_boxes(master, times)
        except Exception:  # noqa: BLE001 - without faces the layout keeps to the uncovered area
            _FACES[key] = []
    return _FACES[key]


def _caption_zone(project):
    """(y0, y1) as fractions: where the Look's burned captions are drawn (the caption feed's own geometry), or None
    when the timeline doesn't say."""
    if not project:
        return None
    try:
        import letitedit.timeline.edit_script as es
        script = es.read(str(project))
    except Exception:  # noqa: BLE001
        return None
    prof = script.get('profile') or {}
    height = float(prof.get('height') or 1920)
    for cap in script.get('captions') or []:
        geo = str((cap.get('style') or {}).get('geometry') or '')
        nums = re.findall(r'(-?[\d.]+)(%?)', geo)
        if len(nums) >= 4:
            y, h = nums[1], nums[3]
            to = (lambda v: float(v[0]) / 100.0) if y[1] else (lambda v: float(v[0]) / height)
            y0, hh = to(y), to(h)
            if 0 <= y0 < 1 and hh > 0:
                return (round(y0, 4), round(min(1.0, y0 + hh), 4))
    return None


def _note_placement(entry, note, placed=True):
    """A file entry of an overlay item says what had to give way in its placement (overlay_layout's note); an item
    the layout could not place is not applied to that file."""
    if not entry.get('applied'):
        return
    if not placed:
        entry['applied'] = False
        entry['why'] = note or delivery.NOT_PLACED
        return
    if note and note not in entry.get('why', ''):
        entry['why'] = (entry.get('why', '') + '; ' if entry.get('why') else '') + note


def final_result(ctx, job_dir, job, attempt, check=lambda: None):
    import letitedit.studio.overlays as overlays
    run = _run(ctx)
    master = Path(run['master'])
    project = _project_of(run['folder'])
    parts = read_project(job, job_dir, project, master, run.get('sources'))
    shared = shared_fields(job, job_dir, project, parts, master, files_made=run.get('made') or [], preview=False,
                           since=run['since'])
    given = None
    if job.get('from_job'):
        r = files.read_json(Path(run['from']) / 'result.json') or {}
        given = overlays.carried(r.get('text_items'))
    result_view = {**shared, 'output': {'files': run.get('made') or []}}
    decided = overlays.decide(_overlay_job(job, run), result_view, duration_s=parts['duration_s'], given=given)
    drawn = run.get('overlay_boxes') or {}
    for t in decided:
        for f in t['overlay']['files']:
            got = (drawn.get(f.get('platform')) or {}).get(t['overlay'].get('from')) if f.get('applied') else None
            if got:
                if got.get('placed'):
                    t.setdefault('box', {k: got[k] for k in ('x', 'y', 'w', 'h')})
                _note_placement(f, got.get('note'), bool(got.get('placed')))
    shared['text_items'] = parts['text_items'] + decided
    proxy, outs = make_proxy(job, job_dir, master, shared, project=project)
    shared['proxy'] = proxy
    deliver = (job.get('inputs') or {}).get('deliver') or {}
    output = {'files': run.get('made') or [], 'project': _rel(job_dir, project),
              'summary': _summary(job, parts, preview=False), 'left_out': parts.get('left_out') or []}
    if deliver.get('post_text'):
        line = _journal_value(run['folder'], run['since'], 'post_text:') or _summary(job, parts, False).split('\n')[0]
        output['post_text'] = {m['platform']: line for m in run.get('made') or [] if m['status'] == 'made'}
    return _result(ctx, job, job_dir, output, shared, (run.get('outs') or []) + outs, project)


# ------------------------------------------------------------------ reading the project

def _rel(job_dir, path):
    return Path(os.path.relpath(Path(path), Path(job_dir))).as_posix()


def _secs(x):
    import letitedit.timeline.edit_script as es
    try:
        return float(es.to_seconds(x))
    except Exception:  # noqa: BLE001
        return 0.0


def _is_footage(path, folder, srcs):
    p = str(Path(path)).lower()
    if srcs and any(p == str(Path(f)).lower() for f in srcs.get('files') or []):
        return True
    roots = [str(Path(r)).lower() for r in ([srcs['folder']] if srcs and srcs.get('folder') else [])
             + (srcs.get('folders') or [] if srcs else [])]
    if any(p.startswith(r + os.sep) or p.startswith(r + '/') for r in roots):
        return True
    return False


def _music_source(path):
    p = str(path).replace('\\', '/').lower()
    for part, source in MUSIC_SOURCES:
        if f'/{part}/' in p:
            return source
    return None


def _asset_licence(x):
    """What a timeline asset's result says of its licence (studio/licences.py): from the library's manifest, the
    download's own sidecar or the producer's receipt; `unknown` when none settles it."""
    return licences.of_asset(x)


def _scene_assets(project, it, span):
    """The assets a code scene on the timeline brings: the scene itself (drawn by code) and each picture its revision
    draws, with that picture's producer's provenance, over the scene's own range."""
    marker = it['scene']
    name = str(it.get('name') or marker.get('id') or 'Code scene')
    out = [{'kind': 'drawn_scene', 'what': name, 'source': 'code_scene', 'ai_generated': False, 'ranges': span}]
    try:
        import letitedit.pictures.code_scenes as code_scenes
        folder = code_scenes.revision_dir(project, marker.get('id'), marker.get('revision'))
    except (ValueError, TypeError, OSError):
        return out
    out[0]['path'] = str(folder.parent.parent)
    for path, got in receipts.scene_parts(folder):
        piece = {'kind': (got or {}).get('kind') or 'picture', 'what': Path(path).stem,
                 'source': (got or {}).get('source') or 'unknown', 'path': path,
                 'ai_generated': bool((got or {}).get('ai_generated')), 'ranges': span, 'in_scene': name}
        web = licences.web_picture(path) if got is None else None
        if web:                                       # a picture fetched from the web, drawn in the scene
            piece.update(kind='web_picture', source=web[0], what=web[2] or piece['what'])
            if web[1]:
                piece['url'] = web[1]
        out.append(piece)
    return out


def read_project(job, job_dir, project, master, srcs=None):
    """What the result says about the video, read from its timeline (letitedit's edit script) and the exported file.
    srcs: the footage New video was given (the run's); a clip from an SDR working copy is named by its original."""
    import letitedit.studio.library as library
    import letitedit.timeline.edit_script as es
    script = es.read(str(project))
    run_sources = srcs
    folder = Path(project).parent
    if run_sources is None:
        try:
            run_sources = resolve_sources(job if not job.get('from_job') else _from_job_spec(job), _home())
        except state.StudioError:
            run_sources = None
    used_tonemapped = False
    info = delivery.probe(master) or {}
    duration = float(info.get('duration_s') or _secs(script.get('length')) or 0.0)
    sources, assets, tracks, cuts, covered = [], [], [], 0, 0.0
    untraced = []
    for t in script.get('tracks') or []:
        kind = t.get('kind') or 'video'
        name = str(t.get('name') or '')
        main = kind == 'video' and name.upper() in ('V1', 'MAIN', 'VIDEO 1')
        for it in t.get('items') or []:
            if isinstance(it.get('graphic'), dict) and not it.get('clip'):       # a recipe: the library assets it draws
                at, length = _secs(it.get('at')), _secs(it.get('len'))
                span = [{'in': round(at, 3), 'out': round(at + length, 3)}]
                assets += licences.graphic_assets(it['graphic'], span)
                pictures, why = receipts.graphic_pictures(it['graphic'], folder)
                for path, got in pictures:               # a picture a letitedit producer made, drawn by the graphic
                    if got['kind'] in ('generated_picture', 'generated_video', 'generated_voice'):
                        assets.append({'kind': got['kind'], 'what': Path(path).stem, 'source': got['source'],
                                       'path': path, 'ai_generated': got['ai_generated'], 'ranges': span})
                if why:                                  # drawn pictures that can't be traced to a maker
                    untraced.append({'in': span[0]['in'], 'out': span[0]['out'], 'why': '; '.join(why)})
                continue
            if isinstance(it.get('scene'), dict):       # a code scene: no clip, its pictures are in its revision
                at, length = _secs(it.get('at')), _secs(it.get('len'))
                if not main and kind == 'video':
                    covered += length
                assets += _scene_assets(project, it, [{'in': round(at, 3), 'out': round(at + length, 3)}])
                continue
            clip = it.get('clip')
            if not clip or not isinstance(clip, str):
                continue
            at, length = _secs(it.get('at')), _secs(it.get('len'))
            a, b = float(it.get('in') or 0.0), float(it.get('out') or 0.0)
            if main:
                cuts += 1
            if _is_footage(clip, folder, run_sources):
                clip, mapped = original_of(run_sources, clip)
                used_tonemapped = used_tonemapped or mapped
                try:
                    fid = library.file_id(clip)
                except OSError:
                    fid = None
                role = 'main' if main else ('audio_only' if kind == 'audio' else 'broll')
                if not main and kind == 'video':
                    covered += length
                rec = {'path': os.path.normpath(clip), 'in': round(a, 3), 'out': round(b, 3), 'role': role,
                       'at': round(at, 3)}
                if fid:
                    rec['file_id'] = fid
                    rec['moment_ids'] = _moments_for(fid, a, b)
                sources.append(rec)
                continue
            span = [{'in': round(at, 3), 'out': round(at + length, 3)}]
            got = receipts.made(clip)                   # the producer's own receipt first
            if got and got['kind'] in ('generated_music', 'written_music'):
                tracks.append({'title': Path(clip).stem, 'source': got['source'], 'path': clip, 'ranges': span})
            elif _music_source(clip):
                tracks.append({'title': Path(clip).stem, 'source': _music_source(clip), 'path': clip, 'ranges': span})
            elif got:
                if not main and kind == 'video':
                    covered += length
                made = {'kind': got['kind'], 'what': Path(clip).stem, 'source': got['source'], 'path': clip,
                        'ai_generated': got['ai_generated'], 'ranges': span}
                made['licence'] = licences.of_asset({**made, 'attribution': got.get('attribution')})
                assets.append(made)
            elif kind == 'audio' or Path(clip).suffix.lower() in AUDIO_EXT:
                lib = _asset_kind(clip) == 'library_sound'
                assets.append({'kind': 'library_sound' if lib else 'other_sound', 'what': Path(clip).stem,
                               'source': 'letitedit_library' if lib else 'unknown', 'path': clip,
                               'ai_generated': False, 'ranges': span})
            else:
                kind_ = _asset_kind(clip)
                if not main and kind == 'video':
                    covered += length
                asset = {'kind': kind_, 'what': Path(clip).stem, 'source': 'letitedit', 'path': clip,
                         'ai_generated': kind_ in ('generated_picture', 'generated_video'), 'ranges': span}
                web = licences.web_picture(clip)
                stock = licences.stock_source(clip) if kind_ == 'stock_video' else None
                if web:                                   # a picture fetched from the web: where it came from
                    asset.update(kind='web_picture', source=web[0], what=web[2] or asset['what'])
                    if web[1]:
                        asset['url'] = web[1]
                elif stock:                               # stock: its source and the page it came from
                    asset.update(source=stock[0], what=stock[2] or asset['what'])
                    if stock[1]:
                        asset['url'] = stock[1]
                assets.append(asset)
    for x in assets:
        x.setdefault('licence', _asset_licence(x))
    captions = caption_cues(script.get('captions'))
    text_items = [{'id': f'cap-{n + 1:03d}', 'kind': 'caption', 'start': round(a, 3), 'end': round(b, 3), 'text': t,
                   'editable': 'live'} for n, (a, b, t) in enumerate(captions)]
    n = 0
    word_caps = []
    for t in script.get('tracks') or []:
        for it in t.get('items') or []:
            g = it.get('graphic') if isinstance(it.get('graphic'), dict) else None
            at, end = round(_secs(it.get('at')), 3), round(_secs(it.get('at')) + _secs(it.get('len')), 3)
            if (g or {}).get('template') == 'word_captions':
                # Word-by-word captions drawn as graphics (a Look's word-pop captions), not a caption feed: they are
                # the video's captions all the same (choices.words_per_min is required).
                said = ' '.join(str(w[0]) for w in ((g.get('params') or {}).get('words') or [])
                                if isinstance(w, (list, tuple)) and w and str(w[0]).strip())
                if said:
                    word_caps.append((at, end, ' '.join(said.split())))
                continue
            words = (g or {}).get('text') or it.get('text')
            if isinstance(words, str) and words.strip():
                n += 1
                text_items.append({'id': f'txt-{n:03d}', 'kind': 'on_screen', 'start': at, 'end': end,
                                   'text': ' '.join(words.split()), 'editable': 'remake'})
            for e in it.get('effects') or []:
                # A text effect on a clip (a hook line on a colour clip): a text filter retext changes in place.
                if isinstance(e, dict) and isinstance(e.get('text'), str) and e['text'].strip():
                    n += 1
                    text_items.append({'id': f'txt-{n:03d}', 'kind': 'on_screen', 'start': at, 'end': end,
                                       'text': ' '.join(e['text'].split()), 'editable': 'live'})
    if not captions and word_caps:
        captions = sorted(set(word_caps))
        # retext can't redraw word-caption graphics yet: it refuses them one by one instead of failing the job
        text_items[:0] = [{'id': f'cap-{k + 1:03d}', 'kind': 'caption', 'start': a, 'end': b, 'text': s,
                           'editable': 'baked'} for k, (a, b, s) in enumerate(captions)]
    words_n = sum(len(t.split()) for _, _, t in captions)
    minutes = max(duration, 1.0) / 60.0
    return {'script': script, 'duration_s': round(duration, 3), 'sources': sources, 'captions': captions,
            'text_items': text_items, 'cuts_per_min': round(max(0, cuts - 1) / minutes, 1),
            'words_per_min': round(words_n / minutes, 1) if words_n else None,
            'broll_share': round(min(1.0, covered / duration), 3) if duration else None,
            'provenance': {'sources': sources, 'assets': assets}, 'untraced': untraced, 'tonemapped': used_tonemapped,
            'music': {'tracks': tracks}, 'left_out': []}


def _from_job_spec(job):
    r = files.read_json(Path(_earlier(job, _home())[0]) / 'job.json') or {}
    return r


def _asset_kind(path):
    p = str(path).replace('\\', '/').lower()
    if '/graphics/' in p or '/graphic' in p:
        return 'graphic'
    if '/made/' in p and ('image' in p or p.endswith(('.png', '.jpg', '.jpeg', '.webp'))):
        return 'generated_picture' if '/made/image' in p else 'drawn_scene'
    if '/made/' in p:
        return 'motion_clip'
    if '/stock/' in p or 'pixabay' in p or 'pexels' in p:
        return 'stock_video'
    if '/sfx/' in p:
        return 'library_sound'
    return 'other'


def _moments_for(fid, a, b):
    """The ids of the index's current moments of this file that overlap a range (none when it was never indexed)."""
    import letitedit.studio.library as library
    ledger = library.read_ledger(_home(), fid)
    return [m['moment_id'] for m in ledger.get('moments') or []
            if m.get('state', 'current') == 'current' and min(m['out'], b) - max(m['in'], a) > 0.2]


def _journal_value(folder, since, prefix):
    """The newest journal note starting with prefix since `since`: its text after the prefix."""
    best = None
    for work in Path(folder).glob('*.letitedit'):
        try:
            lines = (work / 'journal.jsonl').read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            text = str(o.get('text') or '').strip()
            if o.get('kind') == 'note' and text.startswith(prefix):
                best = text[len(prefix):].strip()
    return best


def _rule_notes(folder, since):
    """{rule id: (status, reason, ranges)} from the AI's `rule:<id>: <status>: <reason> @a-b` notes."""
    out = {}
    for work in Path(folder).glob('*.letitedit'):
        try:
            lines = (work / 'journal.jsonl').read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            for text in str(o.get('text') or '').splitlines():
                m = re.match(r'\s*rule:([^:\s]+):\s*(applied|not_applicable|not_met|could_not_check)\s*:?\s*(.*)$',
                             text.strip())
                if not m or o.get('kind') != 'note':
                    continue
                reason, ranges = m.group(3), []
                for a, b in re.findall(r'@\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', reason):
                    ranges.append({'start': float(a), 'end': float(b), 'note': ''})
                reason = re.sub(r'@\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?', '', reason).strip(' ;,.') or None
                out[m.group(1)] = (m.group(2), reason, ranges)
    return out


def rules_field(job, job_dir, folder, since, master, preview):
    rules = (job.get('inputs') or {}).get('rules')
    if rules is None and job.get('from_job'):
        try:
            rules = (_from_job_spec(job).get('inputs') or {}).get('rules')
        except state.StudioError:
            rules = None
    notes = _rule_notes(folder, since) if not preview else {}
    out = []
    for r in rules or []:
        got = notes.get(r['id'])
        if got:
            status, reason, ranges = got
            entry = {'id': r['id'], 'status': status, 'how': 'ai_review'}
            if status != 'applied':
                entry['reason'] = reason or "The AI's review gave no reason."
            elif reason:
                entry['note'] = reason
            yielded = gave_way_to(r, reason, rules) if status == 'not_applicable' else []
            if yielded:                                # a prefer that gave way to another rule (contract 1.5)
                entry['gave_way_to'] = yielded
            if ranges:
                for x in ranges:
                    x['note'] = x['note'] or (reason or r.get('text') or r['id'])[:120]
                entry['ranges'] = ranges
        elif preview:
            entry = {'id': r['id'], 'status': 'could_not_check', 'how': 'not_checked',
                     'reason': 'A preview is the rough cut: blurs and the review come in the final.'}
        else:
            entry = {'id': r['id'], 'status': 'could_not_check', 'how': 'not_checked',
                     'reason': 'The review left no note on this rule, so letitedit cannot say whether it was met.'}
        if entry['status'] in ('applied', 'not_met') and master:
            frames = []
            spans = entry.get('ranges') or []
            for k, span in enumerate(spans[:3]):
                at = (span['start'] + span['end']) / 2
                dst = Path(job_dir) / 'evidence' / f"{r['id']}-{k + 1}.jpg"
                try:
                    delivery.frame(master, at, dst)
                    import letitedit.studio.media_privacy as media_privacy
                    media_privacy.ensure_clean(dst)
                    frames.append({'path': _rel(job_dir, dst), 'at': round(at, 2), 'note': span.get('note') or ''})
                except state.StudioError:
                    continue
            if frames:
                entry['frames'] = frames
        out.append(entry)
    return out


def review_field(folder, since, preview):
    if preview:
        return {'verdict': 'not_reviewed', 'plain': 'A preview is the rough cut, not reviewed: the final is.'}
    bundle = _review_bundle(folder, since)
    if bundle is None:
        return {'verdict': 'incomplete', 'plain': 'No review of the final export was found.'}
    data = files.read_json(bundle) or {}
    rv = files.read_json(bundle.parent / 'review.json') or {}
    verdict = str(data.get('verdict') or rv.get('verdict') or (data.get('gate') or {}).get('verdict') or 'incomplete')
    plain = ''
    md = bundle.parent / 'review.md'
    if md.is_file():                                   # review.md's "For the person" section is the final word
        text = md.read_text(encoding='utf-8', errors='replace')
        m = re.search(r'(?ims)^##\s*(?:for the person|in plain words|plain)[^\n]*\n(.+?)(?=^##\s|\Z)', text)
        plain = m.group(1).strip() if m else ''
    counts = {k: 0 for k in ('critical', 'major', 'minor')}
    told = data.get('counts') if isinstance(data.get('counts'), dict) else None
    if told:                                           # the bundle's own count: the critic's and the checks' findings
        counts.update({k: int(told.get(k) or 0) for k in counts})
    else:
        for p in rv.get('problems') or rv.get('issues') or []:
            if str(p.get('kind') or '').strip().lower() == 'preference':
                continue                               # a note on a preference, never counted (the review's rule)
            sev = str(p.get('severity') or '').lower()
            if sev in counts:
                counts[sev] += 1
    out = {'verdict': verdict if verdict in ('ready', 'revise', 'incomplete', 'blocked') else 'incomplete',
           'plain': plain[:2000], 'path': None, **counts}
    not_checked = [{'check': str(n['check']), 'why': str(n.get('why') or '')[:500]}
                   for n in data.get('not_checked') or [] if isinstance(n, dict) and n.get('check')]
    if not_checked:                                    # the checks the review couldn't do (contract 1.3)
        out['not_checked'] = not_checked
    critic = {k: rv.get(k) for k in ('engine', 'model', 'effort') if rv.get(k)}
    if critic:
        out['critic'] = critic
    return out, md if md.is_file() else None


def _ai_labels(parts, plats):
    a = parts['provenance']['assets']
    pic = any(x.get('ai_generated') and x['kind'] in ('generated_picture', 'generated_video') for x in a)
    voice = any(x.get('ai_generated') and x['kind'] == 'generated_voice' for x in a)
    music = any(t.get('source') == 'ai_made' for t in parts['music']['tracks'])
    items = [{'what': x['what'], 'kind': x['kind'], 'realistic': x['kind'] in ('generated_picture', 'generated_video'),
              'start': x['ranges'][0]['in'], 'end': x['ranges'][0]['out']}
             for x in a if x.get('ai_generated') and x.get('ranges')]
    any_ai = pic or voice or music
    untraced = parts.get('untraced') or []
    why = ('It has AI-made picture or sound; the platform asks for a label on realistic AI media.' if any_ai else
           'No AI-made picture, voice or music is in it.' if not untraced else '')
    if untraced:                                  # a graphic draws a picture letitedit can't trace to its maker
        first = untraced[0]
        why = (why + ' ' if why else '') + (
            f"Whether it is AI-made is not known for a graphic at {first['in']:g}-{first['out']:g} s: {first['why']}"
            + (f" (and {len(untraced) - 1} more)" if len(untraced) > 1 else '') + '.')
    return {'generated_picture': pic, 'generated_voice': voice, 'generated_music': music,
            'altered_real_footage': False, 'items': items,
            'platforms': {p: {'label': ('required' if (pic or voice) else 'unknown' if (music or untraced) else 'not_required'),
                              'why': why, 'rule_as_of': '2026-11'} for p in plats}}


def _music_field(job, parts):
    tracks = []
    for t in parts['music']['tracks']:
        tracks.append({'title': t['title'], 'source': t['source'],
                       'licence': licences.of_song(t['source'], t.get('path')), 'ranges': t['ranges']})
    policy = (job.get('inputs') or {}).get('music')
    if not policy:
        met = 'no_policy'
    elif policy.get('mode') == 'none':
        met = 'yes' if not tracks else 'no'
    elif policy.get('allowed_sources'):
        allowed = set(policy['allowed_sources']) | {'written'}
        met = 'yes' if all(t['source'] in allowed for t in tracks) else 'no'
    else:
        met = 'could_not_check'
    return {'tracks': tracks, 'policy_met': met}


def _brief(folder):
    for work in Path(folder).glob('*.letitedit'):
        b = files.read_json(work / 'brief.json')
        if isinstance(b, dict):
            return b
    return {}


def _hooks_h0(folder):
    for work in Path(folder).glob('*.letitedit'):
        h = files.read_json(work / 'hooks.json') or {}
        for c in h.get('candidates') or h.get('items') or []:
            if isinstance(c, dict) and (c.get('id') == 'h0' or c.get('hook_id') == 'h0'):
                return c
    return {}


def choices_field(job, folder, parts, run_look=None):
    import letitedit.studio.capabilities as capabilities
    inp = job.get('inputs') or {}
    brief = _brief(folder)
    look_id = brief.get('look') or inp.get('look_id') or run_look
    names = {lk['id']: lk['name'] for lk in capabilities.looks_list()[0]}
    idea = inp.get('idea') or {}
    h0 = _hooks_h0(folder)
    approach = h0.get('approach') or h0.get('kind')
    first_caption = parts['captions'][0][2] if parts['captions'] else ''
    hook_line = idea.get('hook_line') or first_caption or None
    main = [s for s in parts['sources'] if s['role'] == 'main']
    seen = f"{Path(main[0]['path']).stem} from {main[0]['in']:g} s" if main else 'drawn pictures'
    first_3s = f'{seen}' + (f'; caption "{first_caption}"' if first_caption else '') + '.'
    tracks = parts['music']['tracks']
    out = {'look_id': look_id if look_id not in ('auto', 'freestyle') else look_id, 'look_name': names.get(look_id),
           'theme_id': inp.get('theme_id'), 'pattern': idea.get('pattern'),
           'hook_kind': HOOK_KINDS.get(str(approach), 'other') if approach else 'other', 'hook_line': hook_line,
           'first_3s': first_3s, 'duration_s': parts['duration_s'], 'cuts_per_min': parts['cuts_per_min'],
           # a Short with no words on its timeline (a montage, silent hands at work) measures 0, not nothing: required
           'words_per_min': parts['words_per_min'] if parts['words_per_min'] is not None else 0.0,
           'caption_style': inp.get('captions') or 'look',
           'music_kind': MUSIC_KINDS.get(tracks[0].get('source'), 'unknown') if tracks else 'none', 'music_mood': brief.get('feel') or None,
           'broll_share': parts['broll_share'],
           'moments': [{'moment_id': m, 'file_id': s['file_id'], 'in': s['in'], 'out': s['out']}
                       for s in parts['sources'] for m in (s.get('moment_ids') or [])[:1]],
           'measured': ['duration_s', 'cuts_per_min', 'words_per_min', 'broll_share', 'moments']}
    return {k: v for k, v in out.items() if v is not None}


def shared_fields(job, job_dir, project, parts, master, files_made, preview, since=0.0):
    run_folder = Path(project).parent
    plats = [m['platform'] for m in files_made if m.get('status') == 'made'] or \
        [p['id'] if isinstance(p, dict) else p for p in (job.get('inputs') or {}).get('platforms') or []]
    shared = {'provenance': parts['provenance'], 'ai_labels': _ai_labels(parts, plats),
              'music': _music_field(job, parts),
              'rules': rules_field(job, job_dir, run_folder, since, master, preview),
              'choices': choices_field(job, run_folder, parts), 'text_items': parts['text_items']}
    got = review_field(run_folder, since, preview)
    if isinstance(got, tuple):
        review, md = got
        if md is not None:
            review['path'] = _rel(job_dir, md)
        shared['review'] = {k: v for k, v in review.items() if v is not None}
    else:
        shared['review'] = got
    return shared


def make_proxy(job, job_dir, master, shared, captions=None, project=None):
    """The phone proxy and its poster (with the overlay items that apply to the proxy, and a preview's captions)."""
    import letitedit.studio.media_privacy as media_privacy
    import letitedit.studio.overlays as overlays
    vid, poster = Path(job_dir) / 'proxy' / 'proxy.mp4', Path(job_dir) / 'proxy' / 'poster.jpg'
    plat = next(iter(shared.get('ai_labels', {}).get('platforms') or {}), 'youtube_shorts')
    faces, zone = _faces(master), _caption_zone(project)
    preview = tier_of(job) == 'preview' and (job.get('inputs') or {}).get('overlay_text')
    if preview:
        decided = overlays.decide(job, {**shared, 'proxy': {'video': 'proxy/proxy.mp4'}, 'output': {'files': []}},
                                  duration_s=(shared.get('choices') or {}).get('duration_s'))
    else:
        decided = [t for t in shared.get('text_items') or [] if t.get('overlay')]
    laid = _placed(decided, plat, 720, 1280, faces, zone, proxy=True)
    items = [i[1] for i in laid if i[1]]
    for t, _, box, used, note in laid:              # each item's own proxy entry, on both tiers
        if preview and box:
            t['box'] = box
        for f in t['overlay']['files']:
            if f.get('proxy'):
                _note_placement(f, note, bool(box))
    if preview:
        shared['text_items'] = [t for t in shared.get('text_items') or [] if 'overlay' not in t] + decided
    made = delivery.proxy(master, vid, poster, overlays=items, captions=captions)
    for p in (vid, poster):
        media_privacy.ensure_clean(p)
    delivery.check_sdr(vid)
    outs = [files.output_entry(job_dir, _rel(job_dir, vid), 'proxy', location_metadata='none',
                               **delivery.describe(vid)),
            files.output_entry(job_dir, _rel(job_dir, poster), 'poster', location_metadata='none')]
    return {'video': _rel(job_dir, vid), 'poster': _rel(job_dir, poster), 'width': made['width'],
            'height': made['height'], 'bytes': vid.stat().st_size}, outs


def _summary(job, parts, preview):
    idea = (job.get('inputs') or {}).get('idea') or {}
    title = idea.get('title') or idea.get('idea_id') or 'The Short'
    first = parts['captions'][0][2] if parts['captions'] else ''
    line1 = f"{title}: {parts['duration_s']:.0f} s" + (f', opening on "{first}"' if first else '') + '.'
    line2 = ('The rough cut, shown as the phone proxy; the final adds the fine cut, the finish and the review.'
             if preview else f"{parts['cuts_per_min']:.0f} cuts a minute; reviewed by letitedit's gate.")
    return f'{line1}\n{line2}'


def _stage_name(job, stage):
    """A cost row's stage: in a preview, what comes after the rough cut is New video's hand-over before it stops."""
    if tier_of(job) == 'preview' and stage not in STAGE_ORDER[:STAGE_ORDER.index(PREVIEW_STOP) + 1]:
        return 'hand_over'
    return stage


def _cost(job, folder, since):
    """tokens, the AI, steps and stages, from the AI's session logs (run_cost.measure): the sessions that ran in this
    job's own window folder, named exactly; else the sessions whose request names the video's folder."""
    import letitedit.app.run_cost as run_cost
    import letitedit.studio.window as window
    try:
        own = run_cost.sessions_under(Path(_home()) / 'windows' / window.instance_for(job['job_id']), float(since))
        m = run_cost.measure(str(folder), float(since), time.time(), sessions=own or None)
    except Exception:  # noqa: BLE001 - unmeasured is said, never guessed
        return {'measured': False}
    total = m.get('total') or {}
    if not total.get('total'):
        return {'measured': False}
    out = {'tokens': {'input': int(total.get('new', 0)), 'cache_write': int(total.get('write', 0)),
                      'cache_read': int(total.get('read', 0)), 'output': int(total.get('out', 0)),
                      'total': int(total.get('total', 0))},
           'steps': int(total.get('steps', 0)), 'usd_api_equivalent': total.get('usd'),
           'stages': [{'stage': _stage_name(job, s['stage']), 'wall_s': round(float(s.get('minutes') or 0) * 60, 1),
                       'tokens': int(s.get('total', 0))} for s in m.get('stages') or []]}
    models = m.get('models') or []
    return {**out, 'measured': True, '_models': models}


def _result(ctx, job, job_dir, output, shared, outs, project):
    run = _run(ctx)
    cost = _cost(job, run['folder'], run.get('first_since') or run['since'])
    import letitedit.studio.window as window
    w = window.StudioWindow(_home(), job, job_dir, _lane(job))
    s = w.settings()
    engine = s.get('engine') or 'claude'
    ai = {'engine': engine, 'model': (cost.pop('_models', None) or [None])[0] or
          (s.get('model') if engine == 'claude' else s.get('codex_model')),
          'effort': s.get('effort') if engine == 'claude' else s.get('codex_reasoning')}
    cost.pop('_models', None)
    cost['ai'] = {k: v for k, v in ai.items() if v}
    extra = {k: v for k, v in shared.items() if k not in ('notes',)}
    if output.get('project') and ((job.get('inputs') or {}).get('deliver') or {}).get('project', True):
        outs = outs + [files.output_entry(job_dir, output['project'], 'project')]
    if shared.get('review', {}).get('path'):
        outs = outs + [files.output_entry(job_dir, shared['review']['path'], 'review')]
    for r in shared.get('rules') or []:
        for f in r.get('frames') or []:
            outs.append(files.output_entry(job_dir, f['path'], 'evidence', location_metadata='none'))
    warnings = [{'code': 'note', 'message': n} for n in shared.get('notes') or []]
    if int(run.get('attempts') or 0) > 1 and cost.get('measured'):
        warnings.append({'code': 'note', 'message': f"The AI ran in {run['attempts']} attempts; the cost counts all of "
                                                    'them.'})
    return {'__result__': True, 'output': output, 'outputs': outs, 'extra': extra, 'warnings': warnings,
            'cost': cost}


def _srt(captions):
    def clock(t):
        ms = int(round(t * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    return '\n'.join(f'{n}\n{clock(a)} --> {clock(b)}\n{t}\n' for n, (a, b, t) in enumerate(captions, 1))
