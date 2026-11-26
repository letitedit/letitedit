"""MCP tool: a full-length review bundle and one delivery verdict for an export (review_bundle.bundle)."""
from __future__ import annotations

from pathlib import Path

import letitedit.review.review_bundle as review_bundle


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_review_bundle(video: str | None = None, kind: str | None = None, project: str | None = None,
                              brief: str | dict | None = None, out: str | None = None, critic: str | None = None,
                              engine: str | None = None, final_of: str | None = None,
                              final: bool = False, render: str | None = None) -> list:
        """Review one export from end to end and decide whether it can be delivered. Covers the WHOLE video: contact
        pages of every part (one frame every 1 s up to 3 min, 2 s up to 15 min, 4 s beyond, each labelled with its
        time), a page of larger frames at the opening, middle, ending and every flagged moment, motion strips of the
        first and last 3 s, 8 s excerpts to watch and listen to, the render's complete transcript, a level graph,
        the gate's measurements, the project's checks (words cut at clip edges including a word's last sound, a last line the source runs straight on from, graphics over captions; with
        project=), the brief's hard requirements (must-keep lines and moments, must-avoid material, exact claims,
        the ending, narration, protected ranges, length; with brief= or a brief.json / journal brief next to the
        project) and, with critic='run', a review that sees all of it from a separate run of an AI on this PC: one
        other than the AI editing when it is available, else the same AI as a fresh session (engine: 'claude' or 'codex'
        to try first); critic=<review.json> uses an existing review. review.md says who reviewed, or why nobody could. Two full rounds
        per video, counted in its side folder: after that critic='run' reuses the last review and the measurements run again;
        critic='again' runs one more. The reviewer reads what earlier rounds found. Each finding has an owner (ai or person) and a fix.
        Returns the verdict, the counts, the findings sorted by severity as one line each (time, severity, source and id,
        the problem and its fix; the first 25), for_you, what wasn't checked, the rounds and the next step, the credit
        lines the video owes for library assets (credits; put them in its description), and the files: review.md, the
        folder, the details page and the contact pages. The evidence, every check's detail, the brief's requirements
        and the measurements are in review.md and review_bundle.json in out (default '<video> review' next to it).
        Findings only the person can act on are returned as for_you and don't set the verdict.
        Verdict: 'blocked' = a critical problem (a required line or moment missing, forbidden material in, a claim
        changed, the reviewer would block); 'revise' = a major problem; 'incomplete' = nothing major found but a
        required check was not done (no editorial review, a failed checker, a stale export, speech the review couldn't
        hear); 'ready' only when all required checks ran clean. A critical or major problem sets the verdict even when
        a check was not done, and the reply's not checked list names it either way. Fix the findings, export, and run it again: your final word to the person is
        review.md, not your own summary. Look at the pages and the details page yourself as well.
        On a preview (letitedit_export preview=True; a render smaller than the project's own size, given project=):
        the size checks judge the project's size, everything else is measured on the preview, and the details page
        is full-size frames of the project from the export engine. final_of=<a reviewed preview>, with video=<the
        final export of the same timeline>: no new review; the final file is checked against the preview (length,
        loudness and true peak, black and frozen stretches, sound and picture in step, the same picture compared
        small, full-size frames in final-frames.jpg), and '<final> review' gets the preview's review with the
        final as its video and what differs as findings. final=True, on a preview: the project's final export
        (letitedit_export's defaults) starts once the measurements are done and renders while the critic reads when
        this bundle is past the round limit (rounds.final); on an earlier round it starts after the review when the
        verdict is ready, and otherwise it isn't started (a final made before the fixes would be replaced).
        final_export in the reply names its job, or says started: false and why.
        render='preview' or 'final', with project= and no video: this call exports the timeline as it stands first
        (letitedit_export preview=True, or its defaults for the full-size final), waits for the file and reviews it;
        render in the reply names the job, the file and the seconds it took. A full-size final reviewed this way is
        the file to deliver: past the round limit it is the last review, and no final_of check follows it. An export
        that doesn't finish is an error naming its job (letitedit_export_job action='resume').
        The review order (settings.json review_code_first, default true; LETITEDIT_REVIEW_CODE_FIRST, 1 or 0, wins):
        with it on, the measured checks run before any critic, two more run (captions drawn in the picture when the
        brief wants captions; caption text inside the covered areas of the platforms the brief names), and
        review_order in the reply and a line of review.md say what the critic did on this call and why: 'held'
        (measured problems the AI fixes first, listed in code_failures: loudness, true peak, black frames, silences,
        words cut at clip edges, a project changed after its export, captions missing, caption text under an app's
        buttons; no critic ran, no round was used), 'reuse' (the export is the file a round already judged, or only
        mechanical changes followed a round that found no picture, story or sound problem: that review stands),
        'look' (one targeted look checks the mechanical notes still open; it says fixed or open for each), 'run'
        (a full critic round: the first, or after a picture, story or sound problem and a change, or after the cut
        changed) or 'as_asked' (critic='again', past the round limit, or no critic asked: the rules above)."""
        r = review_bundle.bundle(video, kind=kind, project=project, brief=brief, out=out, critic=critic,
                                 engine=engine, final_of=final_of, final=final, render=render)
        files = r['files']
        summary = review_bundle.reply(r)
        shown = (files.get('final_frames') if r.get('final_check') else None) or files['details'] or (
            files['pages'][0]['file'] if files['pages'] else None)
        out_list = []
        if shown and Path(shown).exists():
            out_list.append(Image(data=Path(shown).read_bytes(), format='jpeg'))
        return out_list + [summary]

    return letitedit_review_bundle
