"""MCP tool: point at something in a clip (annotate.py) - plan, preview, apply, refresh, list."""
from __future__ import annotations

import json
from pathlib import Path

import letitedit.pictures.annotate as annotate

_BIG = 6000          # a change list longer than this (characters of JSON) comes back with the per-frame data elided


def _compact(plan):
    """The plan as returned to the caller: everything, except bulky per-frame geometry when it is long (the full
    changes stay in the plan file and are applied with plan_id)."""
    out = {k: v for k, v in plan.items() if k not in ('protected',)}
    out['protected'] = [{k: v for k, v in r.items() if k in ('name', 'box', 'source')} for r in plan.get('protected') or []]
    text = json.dumps(plan.get('changes'), default=str)
    if len(text) > _BIG:
        changes = json.loads(text)
        for c in changes:
            item = c.get('item') or {}
            prm = ((item.get('graphic') or {}).get('params')) or {}
            if 'geom' in prm:
                prm['geom'] = (f"<{len(prm['geom']['keys'])} per-frame keys for {prm['geom']['n']} frames; full "
                               f"changes in {annotate.WORK / 'plans' / (plan['plan_id'] + '.json')}>")
            if 'protect' in prm:
                prm['protect'] = f"<{len(prm['protect'])} protected regions>"
        out['changes'] = changes
        out['changes_note'] = 'per-frame data elided; apply this exact plan with letitedit_annotate(plan_id=..., apply=True)'
    return out


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_annotate(project: str, clip: str | None = None, target: list | None = None, kind: str = 'ring',
                         text: str | None = None, at: float | None = None, source_range: list | None = None,
                         timeline_range: list | None = None, duration: float | None = None, space: str = 'display',
                         units: str = 'fraction', follow: str = 'static', freeze: bool = False,
                         style: dict | None = None, protect: list | None = None, platform: str | None = None,
                         track: str | None = None, lost: str = 'hide', track_result: str | dict | None = None,
                         tracking: dict | None = None, apply: bool = False, plan_id: str | None = None,
                         expected_revision: str | None = None, refresh: bool | list | None = None,
                         list_only: bool = False, preview: bool = True, label: str | None = None) -> list:
        """Point at something in a clip - a ring, arrow, box, callout label or magnified detail - from coordinates in
        the clip's OWN source picture. The software maps them through everything the timeline does to that clip (the
        file's orientation flag and any editor rotation override, Crop: Source, Size/Position/Rotate and zoom - static
        or keyframed, fit/fill/distort, alignment, rotation - mirror/flip, the fit into the project frame, trims and
        timeline position) to output pixels, using the export engine's own arithmetic; you never compute positions.
        The annotation is an ordinary editable graphic clip on a video track (default 'Annotations', added if
        missing): its recipe keeps the text, style and the source relationship (clip id, file, source range, target),
        so wording/style change later with letitedit_timeline_apply {op: set, id, graphic: {params: {text, style}}}, and
        refresh re-solves it after the clip is trimmed, moved, cropped or zoomed.

        Plan (default; nothing in the project changes):
          project: .mlt path or episode/cut folder.  clip: the clip id (letitedit_timeline_read).
          target: [x0, y0, x1, y1] box or [x, y] point in the clip's picture at source time `at`.
            units: 'fraction' (0-1 of the picture, as letitedit_track) [default] | 'px' (source pixels).
            space: 'display' (upright, as players and frame tools show the file) [default] | 'coded' (the stored
            pixel grid before the orientation flag).
          kind: ring [default] | arrow | box | label (dot + leader + text; needs text) | magnify (ring + a round inset
            of the detail, from the source at full resolution).  text: label text (optional except for 'label').
          when: source_range [a, b] (seconds in the clip's file) | timeline_range [a, b] (timeline seconds) | at +
            duration (default 3 s from at, or from the clip's start). Clipped to where the clip is seen; `at` (source
            seconds, default the range start) is when the target box is true.
          follow: 'static' [default: the target stays where it is in the source picture; a tracker estimates how far
            the object moves away and warns] | 'track' (follow it with the tracker, av_tools.track/VitTrack, from the
            box at `at`, forwards and backwards). track_result: an existing letitedit_track result (dict or its JSON
            path) for this clip's file instead of tracking again. tracking: {min_score 0.35, max_jump 0.12 (share of
            the picture per frame), max_grow 3, recover_frames 4, smooth 5, hold_s 0.5}.
          lost: what tracking loss does - 'hide' [default: the pointer fades out before the lost frames and is never
            drawn on them] | 'hold' (keep the last sure place up to hold_s, dimmed) | 'stop' (end at the first loss).
          freeze: true = hold the picture at `at` for the annotation (an overlay of the clip's own frame rendered by
            the export engine, grade included; the sound runs on) - freeze-and-label.
          style: {color 'secondary' (a Look colour name or '#RRGGBB'), outline 'dark', label_fill 'dark',
            label_text 'light', label_opacity 0.88, font 'heading' (Look role or family), size 44 (label text at
            1080p), stroke 7, pad 0.3 (ring/box clearance), min_radius 36, arrow 150 (length at 1080p), inset 0.36
            (magnifier diameter, share of the frame's shorter side), zoom (magnifier; default fits the object),
            live false (magnifier: frame by frame instead of the still at `at`), dim 0 (0-1 spotlight), fade_in 0.3,
            fade_out 0.25, pop true, label_side auto|right|left|above|below|above_right|..., margin 0.035}.
          protect: regions the label/inset must avoid: [x0, y0, x1, y1] (frame fractions, or pixels) or {box,
            start_s?, end_s? (timeline), name?}. Also avoided automatically: burnt-in captions while on screen, other
            graphics on screen (titles, animated captions, other annotations), faces in the rendered frames, and a
            platform's covered areas with platform='youtube_shorts' | 'tiktok' | 'instagram_reels' | ....
          track: the video track for it [Annotations]; if busy then, the next 'Annotations 2'...
          preview: render frames with the export engine (melt) and check them [true].
        Returns [preview sheet (frames after the pop-in, middle, near the end), tracking sheet when tracked, result]:
          schema_version, plan_id, project, project_revision (file hash), source_fingerprints, annotation_id,
          changes (edit ops for letitedit_timeline_apply: add_track if needed + insert {graphic: {template: custom,
          params: the recipe}} at the first frame; long per-frame data is elided here and kept in the plan file),
          frames/timeline_range/source_range, target (source box px, where it lands in the output at a few moments),
          transform (orientation, every effect on the clip and whether it was mapped/neutral/assumed, the steps at
          the middle, scale, rotation), layout (label/inset box and side, follow/anchored), hidden_ranges (frames
          where the pointer is not drawn and why: lost, cropped away, out of frame, covered by a clip above),
          lost_ranges (tracking; source + timeline seconds), motion_check, protected, checks (per rendered frame:
          object_in_render = the object found from the pixels by matching its look at `at` - found/predicted/
          error_px/score/verdict matched|weak|ambiguous|not found; tracked_patch_in_render for tracked ones;
          pointer_drawn_at / pointer_vs_plan_px / pointer_to_object_px measured from the render with vs without the
          annotation), check_summary, checked_ranges / unchecked_ranges, warnings (incl. 'unresolved: ...' when a
          label can't avoid something), unsupported, preview_artifacts (sheet, frames, preview project, graphic file),
          recipe (editable recipe and how to edit it).
        Apply: apply=True with the plan arguments plans and applies in one call; plan_id=... with apply=True applies
          that exact earlier plan. Refused if the project file (or a source file) changed since the plan was made
          (expected_revision overrides the plan's revision). Applies to the file (one history copy; letitedit_timeline_
          undo restores it) or, when the project is open in Shotcut, as one undo step there. Returns the plan and
          the apply result.
        Refresh: refresh=True (every annotation) or [ids] re-plans existing annotations from their stored recipes
          against the timeline as it is now; returns per annotation status (up to date | changed | gone |
          unsupported) and the ops (set/move/delete); apply=True applies them.
        list_only=True: the annotations in the project (id, track, at, len, kind, text, source).
        Refused (nothing changed, the reason says why): clips at another speed, reversed or time-remapped clips,
        made clips (ffmpeg graphs, freezes), graphics, effects that warp or shake the picture (stabilize, lens
        correction, corner pin, distort, 360...), two Size/Position effects or two Crop: Source on one clip,
        whole-track picture effects, mirrored orientation flags, EXIF-rotated photos, 1088-line encodings in a 16:9
        project, a range where the clip isn't, a target that is never visible."""
        try:
            if list_only:
                return [{'annotations': [{k: v for k, v in a.items() if k != 'params'} for a in annotate.annotations(project)]}]
            if refresh:
                ids = None if refresh is True else refresh
                res = annotate.refresh(project, ids=ids, preview=preview)
                if apply and res['changes']:
                    res['applied'] = annotate.apply_plan(res['plan_id'], expected_revision=expected_revision,
                                                         label=label or 'annotate: refresh')
                sheets = [r['preview'] for r in res['annotations'] if r.get('preview')]
                return [Image(data=Path(s).read_bytes(), format='jpeg') for s in sheets[:4]] + [res]
            if plan_id and not clip:
                if not apply:
                    return [annotate.load_plan(plan_id)]
                plan = annotate.load_plan(plan_id)
                result = annotate.apply_plan(plan, expected_revision=expected_revision, label=label)
                return [{'plan_id': plan_id, 'applied': result, 'annotation_id': plan.get('annotation_id')}]
            if not clip or target is None:
                raise ValueError('give clip and target to plan an annotation (or plan_id, refresh, list_only)')
            plan = annotate.build(project, clip, kind=kind, target=target, at=at, source_range=source_range,
                                  timeline_range=timeline_range, duration=duration, text=text, space=space,
                                  units=units, follow=follow, freeze=freeze, style=style, protect=protect,
                                  platform=platform, track=track, lost=lost, track_result=track_result,
                                  tracking=tracking, preview=preview, verify=preview)
            out = _compact(plan)
            if apply:
                out['applied'] = annotate.apply_plan(plan, expected_revision=expected_revision, label=label)
            imgs = []
            art = plan.get('preview_artifacts') or {}
            if art.get('sheet'):
                imgs.append(Image(data=Path(art['sheet']).read_bytes(), format='jpeg'))
            if (plan.get('tracking') or {}).get('sheet'):
                imgs.append(Image(data=Path(plan['tracking']['sheet']).read_bytes(), format='jpeg'))
            return imgs + [out]
        except annotate.Unsupported as e:
            return [{'schema_version': annotate.SCHEMA, 'unsupported': [str(e)], 'changes': [],
                     'note': 'nothing was changed'}]
        except (FileNotFoundError, ValueError, KeyError) as e:
            return [{'error': str(e)}]
        except Exception as e:
            import letitedit.timeline.edit_script as es
            if isinstance(e, es.Conflict):
                return [{'error': str(e), 'stale': True, 'note': 'nothing was changed; plan again'}]
            raise

    return letitedit_annotate
