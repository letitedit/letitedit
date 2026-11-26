"""MCP tool: reframing solver (reframe.py) - plan, preview, offers (split / inset), apply."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import letitedit.pictures.reframe as reframe

_BIG = 9000          # a result longer than this (characters of JSON) comes back with keyframe lists elided


def _elide_keys(obj, plan_id):
    """Keyframe lists in effects replaced by their count (the full ops stay in the plan file, applied by plan_id)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == 'size_position' and isinstance(v, dict) and isinstance(v.get('keys'), list) and len(v['keys']) > 6:
                out[k] = {'keys': v['keys'][:2] + [f'... {len(v["keys"]) - 3} more keys (full list in the plan file '
                                                    f'{reframe.WORK / "plans" / (plan_id + ".json")}) ...'] + v['keys'][-1:]}
            else:
                out[k] = _elide_keys(v, plan_id)
        return out
    if isinstance(obj, list):
        return [_elide_keys(v, plan_id) for v in obj]
    return obj


def _compact(plan):
    text = json.dumps(plan, default=str)
    if len(text) <= _BIG:
        return plan
    out = _elide_keys(copy.deepcopy(plan), plan['plan_id'])
    out['changes_note'] = ('keyframe lists are shortened here; apply this exact plan with letitedit_reframe(plan_id=..., '
                           'apply=True), or read the full ops from the plan file')
    return out


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_reframe(project: str | None = None, items: list | None = None, file: str | None = None,
                        source_range: list | None = None, target: str | None = None, keep: list | dict | None = None,
                        priorities: dict | None = None, sources: list | None = None, platform: str | None = None,
                        zoom: float | list | None = None, margin: float | None = None, calm: float | None = None,
                        settings: dict | None = None, cuts: list | dict | None = None, offers: list | None = None,
                        offer_scope: str = 'spans', preview: bool = True, apply: bool = False,
                        plan_id: str | None = None, choose: dict | None = None,
                        expected_revision: str | None = None, label: str | None = None) -> list:
        """Reframe clips to another shape (9:16, 4:5, 1:1, 16:9, any size) keeping several things in frame at
        once - faces, hands, the part being shown, anything you name - on a smooth, mostly still crop path; where
        the things that must stay can't share one crop, it says when and which, and offers a split (two crops
        stacked) or an inset (picture in picture) as ready edits.

        What it finds per moment (boxes in the upright source picture): faces (YuNet), motion with the camera's
        own movement taken out ('action': in hands-on footage the hands and the tool), saved letitedit_track results
        for the file, the boxes you give (followed with VitTrack; where the tracker loses one it is carried with
        the camera's measured motion for up to 2 s, and the plan lists the stretches it was lost), and 'aim' (the
        picture's middle, where no required subject is in view: the crop rests there instead of chasing stray
        motion). The crop path is one linear program per clip: L1 costs on speed,
        acceleration and jerk (holds, then gentle moves), a weak pull towards the subjects' centre, and every
        subject kept inside with margins (required >> preferred >> optional), inside the platform's uncovered area
        when platform is given; the crop never leaves the picture, zoom stays within `zoom`, and the path may jump
        at the clip's own cuts. The path is written as a keyframed Size, Position & Rotate effect
        ({size_position: {keys}}), and coverage is measured frame by frame on those keys with the engine's own
        keyframe arithmetic.

        Modes:
          project: a .mlt (or episode/cut folder) - its clips are reframed to the project's own frame (make a project
            or a linked version of the target size first: letitedit_versions(..., reframe={'mode': 'solve', ...}) does
            this reframe while making a version). items: clip ids (default: every footage clip on a video track whose
            picture shape differs from the frame).
          file + source_range [a, b] (seconds of the file) + target ('9:16' | '4:5' | '1:1' | '16:9' | 'WxH' | a
            platform id): plans one range without a project; returns the item ({clip, in, out, effects}) to insert.
        What to keep:
          keep: in rank order (first = kept when not everything fits). Each entry is a name - 'face', 'hands' /
            'action', 'tracked', or the label of a given box - or a given box {label, box: [x0, y0, x1, y1], at:
            source s} / {label, boxes: [[t, x0, y0, x1, y1], ...]}, units 'fraction' (0-1 of the upright picture,
            default) or 'px', follow 'track' (VitTrack from each given box: between two given boxes forwards from one
            and backwards from the next, joined; default) | 'keys' (straight lines between the given boxes) |
            'static', priority (default required); or the short form [box, label, priority(, at)]. Named subjects are required; found subjects you don't name become optional. Per clip:
            {clip id: [...], '*': [...]}. Without keep: given > tracked > faces (required) > action (optional).
          priorities: {subject id | label | kind: 'required' | 'preferred' | 'optional' | 'ignore'} (per clip:
            {clip id: {...}}), e.g. {'face': 'optional'} lets the face leave.
          sources: automatic finders ['face', 'action', 'track', 'aim'] (default all four); [] for given boxes
            only.
          platform: 'youtube_shorts' | 'tiktok' | 'instagram_reels' | ...: required subjects are kept out of its
            covered areas (bands at the frame edges, platforms.load(...)['safe_zones']).
        How it moves: zoom: 1 (default: the largest crop that fills the frame) or [min, max] (e.g. [1, 1.4]: may
          zoom in up to 1.4x when the subjects fill a tighter crop). margin: space kept around required subjects,
          share of the crop's shorter side (0.04). calm: multiplies the motion costs (2 = fewer, gentler moves). cuts:
          extra source times where the path may jump (the clip's own cuts are found). settings: any reframe.DEFAULTS
          value (max_speed 1 crop width/s and max_accel 1 crop width/s2 - the crop's motion limits, 0 = none;
          recentre_s, headroom, lookahead_s, rejoin_s, min_span_s, span_pad_s, solve_hz, ease, key_tolerance_px,
          face_hz, face_min_score, action_hz, action_min, action_max_area, track_hz, carry_lost_s, ...).
        Offers: offers ['split', 'inset'] (default both; [] for none) for clips where required subjects can't share
          one crop; offer_scope 'spans' (default: only those moments, padded) or 'item' (the whole clip). split:
          the frame halved along its long side, the clip shows one group in one half, a muted copy on track
          'Reframe split' shows the other through Crop: Rectangle; inset: the clip keeps the top-ranked subjects,
          a muted copy on track 'Reframe inset' shows the others in a rounded corner panel the kept subjects use
          least. Both are ordinary items and effects (editable after).
        Apply: apply=True plans and applies in one call; plan_id=... with apply=True applies that exact plan. choose:
          {clip id: 'crop' | 'split' | 'inset'} ('*' for every clip that has that offer); default 'crop' for all.
          Refused when the project or a source file changed since the plan (expected_revision overrides). Applied
          through the shared path: one undo step in an open window, else the file with a history copy
          (letitedit_timeline_undo restores it). Nothing is written without apply.
        Returns [preview sheet, result]. The sheet: per moment the source frame with the crop (white), its path
          (cyan) and the subject boxes (red required, yellow preferred, grey optional), the frame the export engine
          (melt) renders, and the split/inset offers rendered where they apply. The result: schema_version, plan_id
          (= result_id), mode, project, project_revision, source_fingerprints, target {width, height, fps,
          platform, uncovered_area}, settings, items (per clip: subjects with priority, rank, share present and
          where they came from; path {keys, key_deviation_px, zoom_range, cuts, solver}; coverage per subject
          {in_frame, in_uncovered_area, out_cant_fit, out_missed} over the frames it is seen; smoothness {max /
          p95 speed px/s, max / p99 acceleration px/s2, max acceleration over 0.2 s, zoom per s, hold_share,
          moves}; cant_fit [{clip, source, timeline, left_out, kept, why, brief}]; effect; offers {split |
          inset: {spans, timeline_spans, panels, in_copy, in_clip, coverage_in_spans, smoothness, changes}};
          changes), changes (the crop for every planned clip, letitedit_timeline_apply ops), offers, cant_fit
          (every clip), render_check (rendered frame vs the planned crop of the source frame: shift_px,
          mean_diff, match), checked_ranges / unchecked_ranges, warnings (e.g. a required subject out of the
          crop, and why), unsupported (clips not reframed and why), preview_artifacts, seconds; applied (with
          apply).
        Refused per clip (listed in unsupported, nothing changed for it): graphics, colour and made clips, reversed
          clips, Time Remap, stills, Crop: Source on the clip, effects that warp or shake the picture (stabilize,
          lens correction, corner pin, distort, 360...), files with mirrored orientation flags or non-square
          pixels, missing media. A size_position, zoom or blur_pad on a clip is replaced by the reframe (warned)."""
        try:
            if plan_id and not (project or file):
                plan = reframe.load_plan(plan_id)
                if not apply:
                    return [_compact(plan)]
                result = reframe.apply_plan(plan, choose=choose, expected_revision=expected_revision, label=label)
                return [{'plan_id': plan_id, 'applied': result, 'chosen': choose or 'crop'}]
            st = dict(settings or {})
            if zoom is not None:
                st['zoom'] = zoom
            if margin is not None:
                st['margin'] = margin
            if calm is not None:
                st['calm'] = calm
            plan = reframe.plan(project=project, items=items, file=file, source_range=source_range, target=target,
                                keep=keep, priorities=priorities, sources=sources, platform=platform, settings=st,
                                cuts=cuts, offers=('split', 'inset') if offers is None else offers,
                                offer_scope=offer_scope, preview=preview)
            out = _compact(plan)
            if apply:
                if plan['mode'] != 'project':
                    out['applied'] = {'note': 'file mode: nothing to apply; insert items[0].item'}
                else:
                    out['applied'] = reframe.apply_plan(plan, choose=choose, expected_revision=expected_revision,
                                                        label=label)
            imgs = []
            sheet = (plan.get('preview_artifacts') or {}).get('sheet')
            if sheet and Path(sheet).exists():
                imgs.append(Image(data=Path(sheet).read_bytes(), format='jpeg'))
            return imgs + [out]
        except reframe.Unsupported as e:
            return [{'schema_version': reframe.SCHEMA, 'unsupported': [str(e)], 'changes': [],
                     'note': 'nothing was changed'}]
        except (FileNotFoundError, ValueError, KeyError) as e:
            return [{'error': str(e)}]
        except Exception as e:
            import letitedit.timeline.edit_script as es
            if isinstance(e, es.Conflict):
                return [{'error': str(e), 'stale': True, 'note': 'nothing was changed; plan again'}]
            raise

    return letitedit_reframe
