"""MCP tool: exact ranges (start/end frames) of what is looked for in footage, with previews and stable ids
(range_search.find)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import letitedit.footage.range_search as range_search


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_find_ranges(query: str | None = None, files: str | list[str] | None = None,
                            example: dict | None = None, around: list[dict] | None = None,
                            range_ids: list[str] | None = None, ranges: dict | list | None = None,
                            count: int | None = None, settings: dict | None = None,
                            previews: Literal['sheets', 'clips', 'both', 'none'] = 'sheets',
                            pad_s: float | None = None, detail: Literal['brief', 'full'] = 'brief',
                            images: int = 2, background: bool = False, out_dir: str | None = None) -> list:
        """Exact time ranges in the person's footage of what you describe: the first and last frame of each moment,
        not a sampled thumbnail. Picture first, so silent moments are found (a hand turning a screw, a dog jumping
        in, a door opening). Nothing is edited; each range comes with an edit_item for letitedit_timeline_apply.

        WHAT TO FIND (one of): query = text describing the picture ('a hand turns the knob on the wall control');
        example = {file, at} (moments that look like that frame); around = [{file, at} | {file, start, end}, ...]
        moments you already roughly know (from a transcript, the footage log, your own look): each is turned into an
        exact range, judged on `query` when given, else on the picture at that moment; range_ids = ids from an
        earlier call: those ranges again (pad_s applies to their edit items).
        WHERE: files = a video file, a folder (not searched below) or a list; ranges = {file: [[start_s, end_s],
        ...]} limits the search to those parts. count = ranges returned (default 8).

        HOW (all numbers in `settings`; any can be changed): a coarse pass scores frames every every_s (0.5 s) with
        the same picture model as letitedit_search (OpenCLIP ViT-B-32; index cached per file); the best candidates
        (candidates, 16) are re-scored at refine_fps (10/s) for window_s (2.5 s) either side; a range is where that
        score stays above baseline + level x (peak - baseline) (level 0.5); edges then move to a motion onset/end
        (snap_motion_s 0.35, motion measured after the camera's own move is removed) and onto cuts (snap_cut_s 0.25;
        a cut inside a range splits it; camera moves are not cuts: shots.detect); ranges are put on the file's
        frame grid; overlapping hits in one file merge (merge_iou 0.3) and ranges split by a short dip join
        (join_gap_s 0.6); a burst of movement just before a still range starts it (lead_in_s 0.8, edge 'motion
        lead-in'). edges: 'picture' (default: the range is where the picture matches the query) or 'motion' (the
        burst of subject movement at that moment, the camera's own move removed: a reach, a jump, a hand turning
        something; edge basis 'movement'). Other settings: frames, min_gap_s, motion_ratio, min_len_s, max_len_s,
        motion_fps, frame_height, clip_height, clip_pad_s.

        RESULT: schema_version, result_id (= plan_id; the same inputs, settings and source files give the same id and
        reuse the stored result), text (one line per range: read this first), ranges, checked_ranges (what was
        searched, with the windows refined), unchecked_ranges (files or parts not searched, and why), warnings,
        unsupported (what this cannot judge), preview_artifacts, changes: [] (nothing edited), result_file (the full
        result as JSON, detail='full' returns it).
        RANGE: range_id (a hash of the source file's content, the first and last frame and the query: the same on
        every call), file, start, end (source seconds of the first and last frame), start_frame, end_frame
        (inclusive, at the file's frame rate), duration, peak_at (the best-matching moment), edit_item {clip, in,
        out} (out is the time after the last frame; pad_s widens it), picture {peak (cosine 0-1 of the best frame
        with the query), coarse, z_file (standard deviations above the file's median), prominence (peak minus the
        local baseline), coarse_rank}, edges [start basis, end basis] ('picture score', 'motion onset', 'motion
        end', 'motion lead-in', 'cut', 'window edge'), motion {inside, before, after (residual motion 0-255),
        camera_speed (frame
        widths per second)}, cuts {inside_split, snapped}, speech ('silent', the words said in the range, or 'no
        transcript'), merged (other hits folded into it), preview {strip: before/start/peak/end/after frames, clip
        when previews includes clips}. These are separate measurements, not one confidence number; compare them.

        images: how many pictures come back inline (the overview first, then range strips; every path is in the
        result). background=True queues the work as a job and returns its job_id (letitedit_jobs action='status';
        outputs.result_file holds the result). out_dir: where results go (default C:\\LetItEdit\\cache\\range-search\\
        <result_id>)."""
        if background:
            inputs = {k: v for k, v in dict(query=query, files=files, example=example, around=around,
                                            range_ids=range_ids, ranges=ranges, count=count, settings=settings,
                                            previews=previews, pad_s=pad_s, out_dir=out_dir).items() if v is not None}
            st = range_search.submit(inputs)
            return [{'job_id': st['job_id'], 'state': st['state'], 'folder': st.get('folder'),
                     'note': "letitedit_jobs(action='status', job_id=...) shows progress; when done, outputs.result_file "
                             'holds the result (the same JSON as detail="full")'}]
        try:
            res = range_search.find(query=query, files=files, example=example, around=around, range_ids=range_ids,
                                    ranges=ranges, count=count, settings=settings, previews=previews, pad_s=pad_s,
                                    out_dir=out_dir)
        except (FileNotFoundError, ValueError) as e:
            return [{'error': str(e)}]
        out = []
        for a in res.get('preview_artifacts') or []:
            if len(out) >= max(0, int(images)):
                break
            if a['kind'] in ('overview', 'sheet') and Path(a['path']).exists():
                out.append(Image(data=Path(a['path']).read_bytes(), format='jpeg'))
        return out + [range_search.compact(res, detail)]

    return letitedit_find_ranges
