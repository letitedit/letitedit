"""overlay_text, words a caller puts on the picture (contract 1.1; CONTRACT.md section 6, 'overlay_text').

Which overlay items apply to which made file, and why, as the result's text_items report it. Standard library only:
the reference fake decides with it now, and each making kind will place what it decides here when that kind runs.
Placing the words (clear of faces and each platform's covered areas, as captions are placed) is the kind's own work.
"""
from __future__ import annotations

CONDITIONS = ('ai_generated_media',)          # the conditions letitedit knows; `if` is an open list
AI_MEDIA_ASSETS = {'generated_picture', 'generated_video', 'generated_voice'}
AI_MUSIC_SOURCES = {'ai_made'}


def items(job, idea=None):
    """(field, item) for the overlay items of a job; for a batch item (idea given), the top level's then its idea's."""
    inp = job.get('inputs') if isinstance(job.get('inputs'), dict) else {}
    out = [(f'inputs.overlay_text.{i}', it) for i, it in enumerate(inp.get('overlay_text') or []) if isinstance(it, dict)]
    if idea is not None:
        index, data = idea
        out += [(f'inputs.ideas.{index}.overlay_text.{i}', it)
                for i, it in enumerate((data or {}).get('overlay_text') or []) if isinstance(it, dict)]
    return out


def carried(text_items):
    """(field, item) for the overlay items an earlier result reports, so a job that continues it without overlay_text of
    its own (a final from a preview, a revise) decides them again for its own files."""
    out = []
    for t in text_items or []:
        ov = t.get('overlay')
        if not isinstance(ov, dict):
            continue
        item = {'text': t.get('text', ''), 'placement': ov.get('placement') or 'safe_area'}
        for k in ('platforms', 'if'):
            if ov.get(k):
                item[k] = list(ov[k])
        out.append((ov.get('from') or 'overlay_text', item))
    return out


CARRIED_MEDIA = ('provenance', 'ai_labels', 'music')


def carry_media(earlier):
    """A retext's media fields (contract 1.2): a retext changes only text, so the picture and sound it delivers are the
    earlier job's, and so are their provenance, AI labels and music: copied from the earlier result. An overlay item
    with `if: ["ai_generated_media"]` is then decided on them again (decide with given=carried(...))."""
    import copy
    return {k: copy.deepcopy(earlier[k]) for k in CARRIED_MEDIA if isinstance((earlier or {}).get(k), dict)}


def is_still(result):
    """An earlier result that is a still or a motion still (its output has sets), whatever kind made it."""
    return (result or {}).get('kind') == 'still' or ((result or {}).get('output') or {}).get('sets') is not None


def ai_generated_media(result):
    """(holds, why): the result's own provenance holds AI-made picture or sound. Counted: an asset marked ai_generated
    whose kind is a generated picture, video or voice (a voice-over or a dub), and a music track whose source is
    ai_made. Not counted: drawn scenes, graphics and motion clips letitedit draws from code, music written as a score
    (source written), stock, the caller's own footage, and a colour grade or a blur."""
    for a in (result.get('provenance') or {}).get('assets') or []:
        if a.get('ai_generated') and a.get('kind') in AI_MEDIA_ASSETS:
            at = (a.get('ranges') or [{}])[0].get('in')
            where = f' at {at:g} s' if isinstance(at, (int, float)) else ''
            return True, f'the result has AI-made media: {a.get("kind").replace("_", " ")} ({a.get("what")}){where}'
    for t in (result.get('music') or {}).get('tracks') or []:
        if t.get('source') in AI_MUSIC_SOURCES:
            return True, f'the result has AI-made music ({t.get("title")})'
    return False, 'the result has no AI-made picture or sound'


def _condition(name, result):
    if name == 'ai_generated_media':
        return ai_generated_media(result)
    return False, f'letitedit does not know the condition "{name}", so it is not met'


def targets(result, job):
    """The files an overlay can land on: [{'platform': id} | {'size': id} | {'proxy': True}]."""
    kind = job.get('kind')
    output = result.get('output') or {}
    if output.get('sets') is not None or kind == 'still':
        plats = [p['id'] if isinstance(p, dict) else p for p in (job.get('inputs') or {}).get('platforms') or []]
        if plats:
            return [{'platform': p} for p in plats]
        return [{'size': s.get('size')} for s in output.get('sets') or []]
    made = [f['platform'] for f in output.get('files') or [] if f.get('status', 'made') == 'made']
    if made:
        return [{'platform': p} for p in made]
    return [{'proxy': True}] if (result.get('proxy') or {}).get('video') else []


def decide(job, result, idea=None, duration_s=None, given=None):
    """text_items for the job's overlay items (or the (field, item) pairs given), each with overlay.files saying per
    file whether it applied and why."""
    out = []
    files_ = targets(result, job)
    job_plats = {p['id'] if isinstance(p, dict) else p for p in (job.get('inputs') or {}).get('platforms') or []}
    still = (result.get('output') or {}).get('sets') is not None or job.get('kind') == 'still'
    end = duration_s if duration_s is not None else ((result.get('choices') or {}).get('duration_s') or 0)
    for n, (field, item) in enumerate(items(job, idea) if given is None else given):
        conds = [_condition(c, result) for c in item.get('if') or []]
        failed = next((why for ok, why in conds if not ok), None)
        held = '; '.join(why for ok, why in conds if ok)
        wanted = item.get('platforms')
        entries = []
        for t in files_:
            if wanted and 'platform' in t and t['platform'] not in wanted:
                applied, why = False, "not one of this item's platforms"
            elif wanted and 'proxy' in t and not (set(wanted) & job_plats or not job_plats):
                applied, why = False, "none of this item's platforms is one of the job's"
            elif failed:
                applied, why = False, failed
            else:
                applied, why = True, held or ("one of this item's platforms" if wanted else 'every file')
            entries.append({**t, 'applied': applied, 'why': why})
        shown = [e['platform'] for e in entries if e['applied'] and 'platform' in e]
        overlay = {'from': field, 'placement': item.get('placement') or 'safe_area'}
        for k in ('platforms', 'if'):
            if item.get(k):
                overlay[k] = list(item[k])
        overlay['files'] = entries
        ti = {'id': f'ovl-{n + 1:03d}', 'kind': 'on_screen', 'start': 0, 'end': 0 if still else end,
              'text': item['text'], 'editable': 'remake' if still else 'live', 'overlay': overlay}
        if len(shown) < len([e for e in entries if 'platform' in e]):
            ti['platforms'] = shown          # not in every file (empty: in none); absent means every file
        out.append(ti)
    return out
