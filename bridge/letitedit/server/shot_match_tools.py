"""MCP tool: match clips' exposure, white balance and tone to a reference shot (shot_match.match)."""
from __future__ import annotations

from pathlib import Path

import letitedit.review.shot_match as shot_match


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_match_shots(project: str, reference: str | None = None, clips: list[str] | str | None = None,
                            frames: int = 5, strength: float = 1.0, limits: dict | None = None,
                            correct: list[str] | None = None, same_scene: bool = False, keep_looks: bool = True,
                            neutral_regions: dict | None = None, ignore_regions: dict | None = None,
                            exclude: list[str] | None = None, apply: bool = False, plan_id: str | None = None,
                            remove: bool = False, label: str | None = None, detail: bool = False) -> list:
        """Make clips look like they were shot with the same camera settings as a reference clip: bounded exposure,
        white-balance and gentle tone corrections, measured on frames rendered by melt (the export engine) and
        written as an editable Color Grading effect on each clip (Shotcut's lift/gamma/gain filter: change it in the
        filter panel or with letitedit_timeline_apply, or take it off; footage files are never touched). SDR only.
        Proposes first; nothing is written unless apply=True.

        Inputs
        - project: a .mlt or episode/cut folder, or 'live'. In an open window the change is one undo step there
          (Ctrl+Z, or letitedit_timeline_undo); otherwise the saved file with a history copy.
        - reference: id of the clip the others should look like (ids from letitedit_timeline_read). Never changed.
        - clips: the clips to match: a list of ids; 'scene' (default): the reference's neighbours on its track, outward
          until a clip measures as a different scene; 'track': every clip on the reference's track. Items that are not
          camera footage (graphics, colours, made clips) are skipped.
        - frames: frames measured per clip, 1-12 (default 5), spread through the clip clear of transitions and fades.
        - strength: 0-1 (default 1), how much of the bounded correction to apply.
        - limits: {exposure_stops: 1.0, white_balance: 0.15 (per channel, 15 %), tone: 0.15 (gamma within x/÷1.15)}.
          A needed correction over its limit is cut to the limit (noted); over twice the limit the clip is left alone
          (difference_too_large). Maxima: 2 stops, 0.5, 0.5.
        - correct: any of ['exposure', 'white_balance', 'tone'] (default all).
        - same_scene: True when you have checked that the clips show the same scene (e.g. with letitedit_check_frames):
          skips the scene-similarity test for clips without shared surfaces (they are still matched gently).
        - keep_looks: True (default) leaves a clip alone when it or the reference has warm low-sun light (golden hour,
          sunset) or is a night picture and the other is not; False matches anyway.
        - neutral_regions: {clip_id: [x0, y0, x1, y1]} or {clip_id: {box: [...], at_s: s from the clip's start}} as
          fractions (0-1) of the whole frame as letitedit_check_frames shows it, on something grey or white: that clip's
          white balance is measured there instead of on automatically found grey pixels (give one on the reference
          and/or the clips).
        - ignore_regions: {clip_id: [[x0, y0, x1, y1], ...]}: areas left out of the measurements (a screen, a lamp, a
          logo burnt into the footage).
        - exclude: clip ids never touched.
        - apply: write the corrections. With plan_id: write that stored proposal, refused (stale) if the project or any
          source file changed since it was measured; without: measure, propose and write in one call.
        - plan_id: a proposal from an earlier call (its plan_id). Without apply it is returned again unchanged.
        - remove: take the shot-match effects off `clips` (a list), or off every clip that has one; nothing measured.
        - label: the undo label (default '<Claude|Codex|letitedit>: match N shots to <reference>').
        - detail: False (default) returns the short report below; True returns everything (also always saved:
          report_file).

        How it works (the full method is in shot_match.py)
        - Every clip is rendered with only its own track showing, burnt-in captions and its text effects off, its
          earlier shot-match effect replaced by a neutral one; measured inside its own picture (black bars, Blur: Pad
          fill and flat dark borders left out) at 480 px, leaving out pixels with any channel >= 94 % (blown) or
          <= 3.5 % (too dark to measure colour).
        - correspondence mode: when a frame of the clip and one of the reference show the same surfaces (ORB features,
          RANSAC homography, >= 30 inliers, >= 25 % inlier ratio, >= 20 % overlap), the gains come from a robust fit
          to the mean colours of 11 px patches that really line up (log-luma detail correlating > 0.9, which exposure
          and white balance cannot change); gamma too, only when the gains alone leave < 0.04 (4 %). When the colours
          need more than one global correction (residual > 0.12 or under 60 % of patches kept: different light across
          the picture) it is not used. Frame pairs fitted one by one must agree (exposure within 0.6 stop, else
          light_changes_in_clip; over 0.3: half strength).
        - statistics mode (no shared surfaces, scene similarity >= 0.80 with chroma overlap >= 0.76, or same_scene):
          white balance from grey pixels (or the neutral region; left alone when the grey pixels disagree: mixed
          light), exposure from luma quantiles neither picture has blown or crushed, no tone change, 60 % of the
          estimate applied. Sampled frames differing by over 1.2 stop (or 0.12 in colour cast): light_changes_in_clip;
          over 0.6 stop: half strength.
        - Brightening may blow at most 2 % more of the picture than the reference has blown. Every proposal is
          rendered with its effect and measured again; if the difference did not get smaller by at least 5 % and 0.1
          it is dropped.

        Output: [the preview sheet (per clip: reference | before | after, the clip's own picture), report]. The report:
        schema_version, mode ('proposal' | 'applied' | 'removed'), project, project_revision (hash of the .mlt),
        plan_id, summary, reference {id, file, timeline_s}, clips: [{id, status ('proposed' | 'corrected' |
        'unchanged' | 'skipped'), reason (a code, below), why (plain words), mode, timeline_s, source_s, correction
        {text, exposure_stops, red_vs_green_pct, blue_vs_green_pct, gamma}, measured_before / measured_after
        {pairs_delta_e (mean CIEDE2000 over the aligned patches: the same surfaces in both; correspondence mode),
        pairs_exposure_stops (+ = the clip is brighter), pairs_red/blue_vs_green_pct; and whole-picture statistics,
        which also move with framing and content: exposure_stops (luma quantiles), red_vs_green_pct /
        blue_vs_green_pct (its grey pixels' cast relative to the reference's), neutral_delta_e (CIEDE2000 between the
        two neutral estimates), skin_delta_e / skin_hue_deg (skin-coloured pixels, when both have some)}, headline
        {metric (pairs_delta_e when there are pairs), before, after}, notes,
        evidence {scene_similarity, chroma_overlap, shared_surfaces}}], changes (the letitedit_timeline_apply ops:
        {op: effects, id, effects: [..., {filter: color, params: {gain_r/g/b, gamma_r/g/b, lift_* 0,
        'letitedit_ai:shot_match': what it matched}}]}), preview_sheets, warnings, unsupported, applied {written,
        where, history, verified: the written clips rendered again and compared with the preview}, how_to,
        report_file (the whole report: per-frame evidence, sampled and unsampled time ranges, source fingerprints).
        Scores are measurements against stated thresholds, not calibrated probabilities; matching measurements is not
        a judgment of taste: look at the sheet.
        Reasons a clip is left alone: unsupported_hdr, unsupported_wide_gamut, unsupported_log, unverified_transfer
        (10-bit+ with no transfer tag), looks_like_log, project_unsupported (not BT.709/601), reference_unsupported,
        reference_unmeasurable, unmeasurable, too_different, intentional_look, difference_too_large,
        light_changes_in_clip, already_matched, negligible, no_measured_improvement, not_editable; skipped: excluded,
        not_footage, outside_scene.
        Undo an apply with letitedit_timeline_undo (or Ctrl+Z in the open window); remove=True takes the effects off
        later."""
        try:
            rep = shot_match.match(project, reference=reference, clips=clips, frames=frames, strength=strength,
                                   limits=limits, correct=correct, same_scene=same_scene, keep_looks=keep_looks,
                                   neutral_regions=neutral_regions, ignore_regions=ignore_regions, exclude=exclude,
                                   apply=apply, plan_id=plan_id, remove=remove, label=label)
        except (FileNotFoundError, ValueError, KeyError, shot_match.StalePlan) as e:
            return [{'error': str(e)}]
        out = rep if detail else shot_match.brief(rep)
        sheets = (rep.get('preview_artifacts') or {}).get('sheets') or []
        if sheets and Path(sheets[0]).exists():
            return [Image(data=Path(sheets[0]).read_bytes(), format='jpeg'), out]
        return [out]

    return letitedit_match_shots
