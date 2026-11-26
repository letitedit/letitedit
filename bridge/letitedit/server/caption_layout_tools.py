"""MCP tool: the caption layout solver (caption_layout.fit / caption_layout.apply_plan)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import json

import letitedit.pictures.caption_layout as caption_layout

REPLY_VIOLATIONS = 120      # violations listed in a detail='full' reply (all of them are in the plan file)
BRIEF_VIOLATIONS = 20       # after-the-fit violations listed in the default reply
BRIEF_UNRESOLVED = 15       # unresolved cues listed in the default reply
BRIEF_CHANGES_CHARS = 12000  # the changes are left to the plan file above this size
# measuring detail a slim reply leaves to the plan file (new_video_stages.slim(), with the switch)
SLIM_LEFT_TO_PLAN_FILE = ('faces', 'timings', 'checked_ranges', 'source_fingerprints', 'preview_artifacts',
                          'work_dir')


def _compact(result):
    """The detail='full' reply: everything, with the violation list cut to the most important ones (the plan file has
    them all)."""
    out = dict(result)
    vs = result.get('violations') or []
    if len(vs) > REPLY_VIOLATIONS:
        order = {'error': 0, 'warning': 1, 'info': 2}
        keep = sorted(vs, key=lambda v: (order.get(v['severity'], 3), v['stage'] != 'before', v['start']))
        out['violations'] = sorted(keep[:REPLY_VIOLATIONS], key=lambda v: (v['stage'], v['start']))
        out['violations_omitted'] = len(vs) - REPLY_VIOLATIONS
    if len(result.get('cues') or []) > 300:
        out['cues'] = result['cues'][:300]
        out['cues_omitted'] = len(result['cues']) - 300
    rc = result.get('render_check')
    if rc and len(rc.get('rows') or []) > 60:
        out['render_check'] = {**rc, 'rows': rc['rows'][:60], 'rows_omitted': len(rc['rows']) - 60}
    return out


def _brief(result):
    """The default reply: the same verdict and plan, with the per-cue detail left to the plan file (plan_file). A long
    video's whole result runs to hundreds of thousands of characters, more than an AI's tool reply can hold."""
    out = {k: v for k, v in result.items() if k not in ('violations', 'cues', 'unresolved', 'render_check', 'changes')}
    order = {'error': 0, 'warning': 1, 'info': 2}
    after = [v for v in result.get('violations') or [] if v.get('stage') == 'after']
    after.sort(key=lambda v: (order.get(v.get('severity'), 3), v.get('start') or 0))
    out['violations_after'] = [{k: v[k] for k in ('kind', 'severity', 'layer', 'cue', 'start_clock', 'end_clock', 'detail')
                                if k in v} for v in after[:BRIEF_VIOLATIONS]]
    if len(after) > BRIEF_VIOLATIONS:
        out['violations_after_omitted'] = len(after) - BRIEF_VIOLATIONS
    unresolved = result.get('unresolved') or []
    out['unresolved'] = [{k: u[k] for k in ('kind', 'layer', 'cue', 'start_clock', 'end_clock', 'why') if k in u}
                         for u in unresolved[:BRIEF_UNRESOLVED]]
    if len(unresolved) > BRIEF_UNRESOLVED:
        out['unresolved_omitted'] = len(unresolved) - BRIEF_UNRESOLVED
    options = {}
    for u in unresolved:
        options.setdefault(u.get('kind'), u.get('options'))
    if any(options.values()):
        out['unresolved_options'] = options
    changes = result.get('changes') or []
    if len(json.dumps(changes)) <= BRIEF_CHANGES_CHARS:
        out['changes'] = changes
    else:
        out['changes_count'] = len(changes)
    rc = result.get('render_check')
    if rc:
        out['render_check'] = {k: v for k, v in rc.items() if k != 'rows'} | {'rows_in_plan_file': len(rc.get('rows') or [])}
    out['detail_in_plan_file'] = ('the whole proposal (every cue, violation before and after, unresolved option, '
                                  "change) is in plan_file; detail='full' returns it here")
    import letitedit.app.new_video_stages as new_video_stages
    if new_video_stages.slim():
        # with the switch (new_video_stages.py): the measuring detail stays in the plan file only
        for key in SLIM_LEFT_TO_PLAN_FILE:
            out.pop(key, None)
        out['detail_in_plan_file'] += ', with ' + ', '.join(SLIM_LEFT_TO_PLAN_FILE)
    return out


def _short(reply):
    import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
    return next_step_replies.caption_fit_reply(reply)


def fit(project, tracks=None, platform=None, output=None, style=None, lock=None, min_size_px=None, protected=None,
        faces='hard', placements=None, prefer=None, regroup='auto', native_mode='tracks', max_lines=None, max_cps=20.0,
        min_duration_s=None, max_duration_s=7.0, keep_together=None, min_gap_em=0.12, peak_gap_em=0.04,
        platform_zones='hard', render_check=True, max_frames=40, apply=False, plan_id=None, expected_revision=None,
        detail='brief'):
    """letitedit_caption_fit without MCP: (the before | after sheet's path or None, the reply). The same arguments
    and defaults as the tool."""
    try:
        if plan_id:
            plan = caption_layout.load_plan(plan_id)
            if not apply:
                plan['stale'] = caption_layout.stale_reasons(plan)
                return None, (_compact(plan) if detail == 'full' else _brief(plan))
            applied = caption_layout.apply_plan(plan, expected_revision=expected_revision)
            if (applied or {}).get('applied'):
                from letitedit.server import caption_follow      # T360: on by default
                caption_follow.remember_applied(plan['project'], plan_id)
            return None, {'plan_id': plan_id, 'project': plan['project'], 'applied': applied,
                          'summary': plan.get('summary'), 'unresolved': plan.get('unresolved')}
        if expected_revision:
            import letitedit.timeline.edit_script as es
            now = es.file_hash(es._resolve(project))
            if now != expected_revision:
                return None, {'error': f'the project changed since revision {expected_revision} (now {now}): read it '
                                      f'again before laying out its captions'}
        result = caption_layout.fit(
            project, tracks=tracks, platform=platform, output=output, style=style, lock=lock,
            min_size_px=min_size_px, protected=protected, faces=faces, placements=placements, prefer=prefer,
            regroup=regroup, native_mode=native_mode, max_lines=max_lines, max_cps=max_cps,
            min_duration_s=min_duration_s, max_duration_s=max_duration_s, keep_together=keep_together,
            min_gap_em=min_gap_em, peak_gap_em=peak_gap_em, platform_zones=platform_zones,
            render_check_frames=render_check, max_frames=max_frames)
        from letitedit.server import caption_follow              # T360: on by default
        args = dict(tracks=tracks, platform=platform, lock=lock, min_size_px=min_size_px, protected=protected,
                    faces=faces, placements=placements, prefer=prefer, regroup=regroup, native_mode=native_mode,
                    max_lines=max_lines, max_cps=max_cps, min_duration_s=min_duration_s,
                    max_duration_s=max_duration_s, keep_together=keep_together, min_gap_em=min_gap_em,
                    peak_gap_em=peak_gap_em, platform_zones=platform_zones)
        caption_follow.remember_fit(result.get('project') or project, result.get('plan_id'), args)
        if apply and result.get('changes'):
            result['applied'] = caption_layout.apply_plan(result, expected_revision=result['project_revision'])
            if (result['applied'] or {}).get('applied'):
                caption_follow.remember_applied(result.get('project') or project, result.get('plan_id'), args)
    except caption_layout.Refused as e:
        return None, {'error': str(e)}
    except (FileNotFoundError, ValueError, KeyError, RuntimeError, caption_layout.Conflict) as e:
        return None, {'error': f'{type(e).__name__}: {e}'}
    reply = _compact(result) if detail == 'full' else _brief(result)
    sheet = next((p for p in result.get('preview_artifacts', []) if str(p).lower().endswith('.png')), None)
    return (sheet if sheet and Path(sheet).exists() else None), reply


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_caption_fit(project: str, tracks: list[str] | None = None, platform: str | None = None,
                            output: str | None = None, style: dict | None = None, lock: list[str] | None = None,
                            min_size_px: float | None = None, protected: list[dict] | None = None,
                            faces: Literal['auto', 'off', 'hard'] = 'hard', placements: list[str] | None = None,
                            prefer: str | None = None, regroup: Literal['auto', 'all', 'none'] = 'auto',
                            native_mode: Literal['track', 'tracks'] = 'tracks', max_lines: int | None = None,
                            max_cps: float = 20.0, min_duration_s: float | None = None, max_duration_s: float = 7.0,
                            keep_together: list[str] | None = None, min_gap_em: float = 0.12,
                            peak_gap_em: float = 0.04, platform_zones: Literal['hard', 'soft', 'off'] = 'hard',
                            render_check: bool = True, max_frames: int = 40, apply: bool = False,
                            plan_id: str | None = None, expected_revision: str | None = None,
                            detail: Literal['brief', 'full'] = 'brief') -> list:
        """Lay out a project's captions so every word reads: line breaks and grouping, size, and a place that keeps
        clear of faces, other text, the platform's buttons and captions, and regions you protect. Measures what the
        renderers actually draw (outline, shadow, the biggest moment of a pop animation), finds words that run
        together, and returns editable changes (letitedit_timeline_apply ops), violations with exact times, before |
        after preview crops from the export engine, and what it could not solve. Writes nothing unless apply=True.
        The approved words are never changed or dropped: only line breaks, grouping, cue edge times, size, place,
        outline and pop strength change (and a lost space where the cached transcript shows two words).

        Caption layers it lays out: native caption tracks burned into the picture (Shotcut's Subtitle Burn In, the
        `captions` of letitedit_timeline_read) and word-by-word caption graphics (a video track of `word_captions`
        graphics, from {op: captions, animate: ...}). A native caption track has ONE place and style for all its
        cues (the burn-in filter draws every cue in one rect); a cue that needs another place goes on a caption track
        of its own with native_mode='tracks' (named '<track> (top)' etc.). Word captions take a place per cue.

        Inputs
        - project: .mlt path or episode/cut folder (the saved file; a window's unsaved changes are not seen).
        - tracks: caption track names to lay out, in order [all visible caption layers]; the others are obstacles.
          A laid-out layer is an obstacle for the layers after it (two text layers never overlap).
        - platform: profile whose covered areas are kept clear: 'phone' (the union of Shorts, TikTok and Reels),
          tiktok, youtube_shorts, instagram_reels, facebook_reels, youtube... (letitedit_platforms lists them; areas carry their own
          confidence). Ignored, with a warning, when the profile's shape differs from the project's.
        - output: export size 'WIDTHxHEIGHT' when it differs from the project frame by scale (sizes are then judged
          at export size); another shape is refused (make that version first with letitedit_versions).
        - style: a look to apply first. Native captions: the captions op's keys (font, fill, outline {color, width}
          or px, shadow {color, x, y}, background) and size (project px). Word captions: the template's params (font,
          size (project px), outline_width, outline, shadow, pop_scale, style pop|karaoke|highlight|typewriter|bounce,
          fill, highlight, uppercase, box).
        - lock: properties the solver must not change: size, outline (outline_width), pop_scale, position,
          center_x, max_width. A problem that needs a locked one is reported as unresolved.
        - min_size_px: smallest readable text size at export size [3.4% of the frame's short side: 37 px at 1080].
          Text is never shrunk below it; a word that can't fit a line above it is unresolved, not shrunk.
        - protected: regions captions must keep clear of: [{box: [x0, y0, x1, y1] (0-1 fractions or pixels), start?,
          end? (s), hard? (true: never covered; false: avoided when possible), name?}], or a moving one {keys: [[t,
          [x0, y0, x1, y1]], ...], ...} (straight-line movement between keys; there from the first key to the last).
        - faces: 'hard' [default] finds faces (OpenCV YuNet) at every caption's middle, every half second across the
          captions and through long captions, and never covers one; 'auto' avoids one when possible; 'off'.
        - placements: allowed places [tall: bottom, low, middle, high, top; wide: bottom, top]: inside the safe area
          (frame margins minus platform overlays), 'bottom' and 'top' hold the text block's edge on the safe edge,
          the others its centre. 'free' (a tall frame with a face): the middle of the room between the lowest chin in
          the video and the bottom of the safe area, one place for the whole video, offered first; the reply's free_area
          gives where it starts and ends (project pixels and % of the frame's height) and, for platform 'phone', what
          each app alone would leave. Where a free place exists the current place is one candidate like the others;
          without one the current place is kept when nothing is wrong with it.
          prefer: the place to lean toward [free where it exists, else the one nearest the current captions].
          One size: a word-caption layer whose cues differ in size is set to its largest.
        - regroup: 'auto' regroups only problem cues and their neighbours (runs past a sentence end or a lost full
          stop like 'it Without', ends on an article, needs too many lines, too short on screen, reads too fast);
          'all' regroups every cue with word timing; 'none' keeps the grouping. Native captions take word times from
          the cached transcript (nothing is transcribed here); cues without them keep their grouping.
        - native_mode: 'tracks' [default] lets cues that need another place go on a caption track of their own;
          'track' keeps one place for the caption track.
        - max_lines [2; 3 when the track already uses 3], max_cps reading speed in characters a second [20, native
          captions], min_duration_s [native 0.8, word captions 0.4], max_duration_s [7], keep_together: phrases never
          split across lines or cues (names like 'Acme Camera' and numbers with units are kept together
          where possible anyway).
        - min_gap_em: clear space needed between neighbouring words, as a share of the text size [0.12], measured on
          the drawn ink with outline and shadow above the baseline (descenders don't count). peak_gap_em: the same
          while a word pops [0.04]. Fixed by thinning the outline / lowering pop_scale layer-wide (as little as
          needed); otherwise unresolved.
        - platform_zones: 'hard' (never under a platform overlay), 'soft' (avoided when possible), 'off'.
        - render_check: render the riskiest frames of the project and of the proposal (compiled into a scratch copy
          in the cache) with melt, measure the captions' own pixels, and cut before | after preview crops [true].
          max_frames: frames rendered for faces and for the render check [40].
        - apply: refused, with both numbers and nothing written, when the plan covers more faces than the captions do
          now (summary before and after, covers_face), or when any word would be lost or moved from when it is said.
          Regrouping replaces caption items, so a plan can delete an item while every word stays. Otherwise: write the
          changes through letitedit_timeline_apply's path (an open Shotcut window gets them as one undo
          step, otherwise the file changes with an undo copy; letitedit_timeline_undo reverts). In an open window the
          regrouped cues and the caption style (place, size, outline, colours) land together as that one undo step.
          A window of an older letitedit build takes cue text and times only: with the project saved, the plan goes
          through the file instead (the window reloads); with unsaved changes in the window, nothing is written and
          the reply says to save first.
          plan_id: apply (or, without apply, show) a proposal made earlier instead of making a new one; it is refused
          when the project, a font, the text engine or the template changed since. expected_revision: the
          project_revision the caller saw; refused when the project has changed.

        - detail: 'brief' [default] replies with the summary, layers, frame, plan_id and plan_file, the first 20
          violations after the fit (violations_after), the first 15 unresolved with one set of options per kind, and
          the changes when they fit in 12,000 characters; every field below is in the file at plan_file whatever this
          says. 'full' puts them in the reply as well, which on a long video can be too big for a tool reply.

        Returns [preview image (when rendered), result]. result (with detail='full'; see detail above):
        - schema_version, project, project_revision (file hash: pass it back as expected_revision), plan_id,
          plan_file (the whole proposal as JSON), source_fingerprints (fonts, engine, template, platform, words).
        - frame: size, shape, platform, safe rect, covered zones (pixels), min_size_px, allowed placements.
        - free_area: {top, bottom, centre, top_pct, bottom_pct, centre_pct, each_platform_alone}, or null when there is
          no face or under 5% of the frame's height of room.
        - layers: per laid-out layer: kind (native|words), cues before/after, font, size, place used, preferred
          place, geometry before/after, style_changes, gap_fix, regrouped_cues, token_fixes (spaces restored),
          tracks_out (caption tracks the layer ends up on).
        - changes: ops for letitedit_timeline_apply ({op: captions, track, cues, style} for native captions;
          {op: set, id, graphic: {params}} / {op: delete} + {op: insert, at, item} for word captions).
        - cues: every cue after the fit: start, end, text (with line breaks), lines, place, position, ink box,
          size_px, regrouped.
        - violations: [{kind, severity, stage (before|after), layer, cue, start, end (+ _clock), at (worst moment),
          detail, measured, limit, box, evidence (melt | template | predicted | melt-footage), other}]. kinds:
          fused_words, fused_at_peak, missing_space, suspected_missing_space, too_small, auto_shrunk (the engine
          shrinks a cue that doesn't fit its rect), too_many_lines, outside_frame, outside_safe, platform_overlay,
          covers_face, covers_text, protected_region, reading_speed, too_short, too_long, overlapping_cues,
          bad_break (info), render_mismatch (info: rendered pixels outside the measured box).
        - summary: violation counts before and after, unresolved count, change count.
        - unresolved: constraints no allowed choice satisfies, with times, why and options (never solved by shrinking
          text below min_size_px).
        - render_check: per rendered moment the captions' pixel box before/after, which obstacles they overlap
          (caption pixels inside each), inside the safe area, and the share of caption pixels outside the measured
          box (render_mismatch above 3%).
        - preview_artifacts: the before | after sheet (PNG) and the folder of full proposal frames.
        - checked_ranges / unchecked_ranges (what was not checked and why: faces not sampled, grouping without word
          timing), warnings, unsupported (layers not laid out and why), faces (samples, faces found), timings.
        - applied (with apply): the apply result and, per layer, whether every word is kept (identical: true)."""
        sheet, reply = fit(project, tracks=tracks, platform=platform, output=output, style=style, lock=lock,
                           min_size_px=min_size_px, protected=protected, faces=faces, placements=placements,
                           prefer=prefer, regroup=regroup, native_mode=native_mode, max_lines=max_lines, max_cps=max_cps,
                           min_duration_s=min_duration_s, max_duration_s=max_duration_s, keep_together=keep_together,
                           min_gap_em=min_gap_em, peak_gap_em=peak_gap_em, platform_zones=platform_zones,
                           render_check=render_check, max_frames=max_frames, apply=apply, plan_id=plan_id,
                           expected_revision=expected_revision, detail=detail)
        if detail != 'full':
            reply = _short(reply)       # the MCP reply only: fit() returns the brief whole to Python callers
        if sheet:
            return [Image(data=Path(sheet).read_bytes(), format='png'), reply]
        return [reply]

    return letitedit_caption_fit
