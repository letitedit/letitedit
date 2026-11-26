"""MCP tool: repeated takes of the same passage, grouped and measured side by side (takes.find)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import letitedit.footage.takes as takes


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_find_takes(files: str | list[str] | None = None, archive: dict | None = None,
                           script: str | list[str] | None = None, phrase: str | None = None,
                           ranges: dict | list | None = None, speaker: str | None = None,
                           speakers: Literal['cached', 'run', 'off'] = 'cached',
                           min_take_s: float | None = None, max_take_s: float | None = None,
                           measures: list[str] | None = None, weights: dict | None = None,
                           names: list[str] | None = None, min_words: int | None = None,
                           min_similarity: float | None = None, recurring: bool | str = True,
                           restarts: bool = True, previews: Literal['sheets', 'clips', 'both', 'none'] = 'sheets',
                           clips_for: list[str] | None = None, context_s: float | None = None,
                           transcribe: bool = False, analyze: bool = False, max_groups: int | None = None,
                           settings: dict | None = None, out_dir: str | None = None,
                           detail: Literal['brief', 'full'] = 'brief', images: int = 2,
                           background: bool = False) -> list:
        """Repeated takes of the same passage in the person's own footage: groups them, shows how their wording
        differs, measures each take on separate components and makes aligned comparison previews, so you (or the
        person) choose the performance. It never picks a winner, never edits a timeline and never deletes anything.
        Works from the cached transcripts (word timings); nothing is transcribed unless transcribe=True.

        SOURCES (one of): files = a video/audio file, a folder (not searched below) or a list; archive = a subset of
        the indexed archive (letitedit_archive's database), one copy per recording, files with talking: {folder,
        exclude_folder, date_from, date_to, place, camera, max_files (default 200)}. ranges = {file: [[start_s,
        end_s], ...]} limits the check to those source seconds.
        WHAT: without script/phrase, every passage said more than once is found. script = the lines meant to be said
        (one per line, or a list): one group per line with every place it is said, compared with the script itself;
        phrase = one phrase to find every time it is said.
        speaker = an id ('S1') or name from letitedit_speakers: only that person's words. speakers: 'cached' (default:
        use a stored letitedit_speakers assignment; then lines are split where the voice changes and two people saying
        the same words are never takes of each other), 'run' (make one with the voice model, GPU), 'off'.
        min_take_s / max_take_s (default 120): duration limits. min_words (default 4) and min_similarity (default
        0.6): how much of a passage two lines must share. names: words that are names (so a change is a claim
        difference). recurring: True (default) lists passages said again far apart only when they repeat a whole line
        with 3+ content words or differ in a claim; 'all' lists every one; False none. restarts (default True): also
        attempts started over inside one line ('I don't | I don't even think | I don't think I need...').
        measures: any of text, delivery, edges, audio, noise, picture, transcript, speaker (default all).
        weights: {component path: weight}, e.g. {'audio.snr_db': 1, 'delivery.pauses.count': -1, 'text.coverage': 2}:
        adds ordered_by_weights to each group (each component min-max scaled 0-1 within the group, times your weight,
        summed). An ordering by your weights, not a verdict; without weights there is no ranking.
        previews: 'sheets' (default: one comparison image per group), 'clips' (a short MP4 per take with context_s,
        default 1.0, before and after, plus a reel of the group's takes back to back), 'both', 'none'; for the first
        12 groups (settings.preview_groups). clips_for = [group ids]: clips just for those groups (ids are stable
        for the same files, transcripts and settings, so call again with them). images: sheets returned inline
        (default 2; every sheet path is in the result). analyze=True computes missing sound/picture/voice analyses
        (slow); otherwise those components say 'available: false' (unknown, not a pass). transcribe=True transcribes
        files with no cached transcript (one at a time). settings: split_pause_s (1.0: a pause this long ends a
        line), long_pause_s (0.6: pauses listed), retake_gap_words (40) and retake_gap_s (300: takes this close count
        as retakes), restart_gap_s (120), query_join_s (3.0), max_groups (40), preview_groups (12), frames (3),
        clip_height (360). background=True queues the work as a job and returns its job_id at once (letitedit_jobs
        action='status' shows progress; outputs.result_file is the result). detail: 'brief' (default) or 'full'.

        RESULT: schema_version, result_id (= plan_id; changes when files, transcripts, analyses or settings change; a
        repeat call with the same inputs reuses the stored result), summary (counts: groups, takes, retakes,
        restarts, recurring, false starts, groups with different claims, differences by kind), text (one block per
        group, one line per take with its measurements: read this first), groups, checked / unchecked_ranges (files
        or stretches not checked and why: no transcript, voice with no words, uncached windows), warnings,
        unsupported (cases this cannot judge), preview_artifacts, changes: [] (nothing is edited), result_file (the
        full result as JSON, with every component, measures_info and source_fingerprints).
        GROUP: group_id, pattern ('retakes': separate lines close together; 'restart': started over inside one line;
        'recurring': said again far apart, other talk between, e.g. a catchphrase or a callback joke; 'mixed'),
        passage (the reference take's words, or the script line), same_claim, claim_kinds, claim_variants
        ([{variant, takes, says}]: takes that differ in a number, negation, name or opposite word are separate
        variants and never the same claim; 'says' quotes the differing words), differences ([{take, vs, kinds, op,
        text, vs_text, at, context}], kinds: number, negation, name, opposite, wording, function = small words only,
        number_format = same number written another way), gaps (seconds and words between consecutive takes), sheet,
        reel, takes.
        TAKE: take (id), label (T1.. in recording order), file, start, end (source seconds), text, reference,
        variant, completeness ('complete' covers 80%+ of the passage, 'partial', 'false_start' = dropped and started
        again), coverage, similarity (0-1, text), matches_script (script mode), edit_item {clip, in, out} (cut points
        snapped to the audio; insert it with letitedit_timeline_apply), context, frames, clip, and (in result_file)
        components: text; delivery (duration_s, words, words_per_s, pauses {count, longest_s, total_s, at}, restarts,
        fillers); edges (lead_in_s / tail_out_s room before/after, first_word_cut_by_recording_start,
        last_word_cut_by_recording_end, cut_in, cut_out, tight_in/out, first/last_word_p); audio (peak_dbfs,
        clipped_samples, clip_runs, clipped_ms, speech_db, noise_db, snr_db, voice_without_words_s,
        words_without_voice_s); noise (impacts, sustained sounds, loud_background); picture (dark, blown_out, blurry,
        shaky shares, camera, cuts_inside, sharpness_vs_clip); transcript (mean_p, min_p, unsure_words: the
        transcriber's own probabilities, a model score, not calibrated); speaker. Loudness is not delivery quality.
        Each group also has look_items for letitedit_look (frames with waveform and word lanes of every take)."""
        if background:
            inputs = {k: v for k, v in dict(files=files, archive=archive, script=script, phrase=phrase,
                                            ranges=ranges, speaker=speaker, speakers=speakers, min_take_s=min_take_s,
                                            max_take_s=max_take_s, measures=measures, weights=weights, names=names,
                                            min_words=min_words, min_similarity=min_similarity, recurring=recurring,
                                            restarts=restarts, previews=previews, clips_for=clips_for,
                                            context_s=context_s, transcribe=transcribe, analyze=analyze,
                                            max_groups=max_groups, settings=settings, out_dir=out_dir).items()
                      if v is not None}
            st = takes.submit(inputs)
            return [{'job_id': st['job_id'], 'state': st['state'], 'folder': st.get('folder'),
                     'note': "letitedit_jobs(action='status', job_id=...) shows progress; when done, outputs.result_file "
                             'holds the result (the same JSON as detail="full")'}]
        try:
            res = takes.find(files=files, archive=archive, script=script, phrase=phrase, ranges=ranges,
                             speaker=speaker, speakers=speakers, min_take_s=min_take_s, max_take_s=max_take_s,
                             measures=measures, weights=weights, names=names, min_words=min_words,
                             min_similarity=min_similarity, recurring=recurring, restarts=restarts,
                             previews=previews, clips_for=clips_for, context_s=context_s, transcribe=transcribe,
                             analyze=analyze, max_groups=max_groups, settings=settings, out_dir=out_dir)
        except (FileNotFoundError, ValueError) as e:
            return [{'error': str(e)}]
        out = []
        for g in res.get('groups') or []:
            if len(out) >= max(0, int(images)):
                break
            p = g.get('sheet')
            if p and Path(p).exists():
                out.append(Image(data=Path(p).read_bytes(), format='jpeg'))
        return out + [takes.compact(res, detail)]

    return letitedit_find_takes
