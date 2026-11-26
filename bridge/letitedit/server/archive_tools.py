"""MCP tool letitedit_archive: search, status and update of the footage archive (archive.py)."""
from __future__ import annotations

from pathlib import Path

import letitedit.footage.archive as archive

DOC = """The footage archive: every clip already indexed on this PC (transcripts, footage log, footage scan, GPS from
the caches) in one local SQLite database (C:\\LetItEdit\\cache\\archive\\archive.sqlite), searched by meaning with
local text embeddings (BAAI/bge-small-en-v1.5, MIT). Copies of a clip in several folders are one clip: with
copies='recording' (default) files with the same content (file size + first 2 MB), or the same file name (case and
a ' (2)' suffix ignored) and the same recording time tag, or the same name and sizes within same_size_frac (default
0.001) of each other; with copies='content' only the same content. The files of a clip lend each other recording
time, camera, place and length.

action 'search' (default): spans like `query` across the whole archive. A span is a stretch of speech (transcript
words split at pauses over pause_s or after span_words words) or one footage log entry (action, things, place,
framing, text, quality). score = meaning (cosine of the query and span vectors) + words_weight (default 0.15) x the
share of the query's words (stop words left out) found in the span's text. Filters: kind 'speech' | 'log' | 'any'
(default 'any'); folder / exclude_folder (a path or list; a file counts when any copy is under it); date_from /
date_to ('YYYY-MM-DD', the recording's local date from the camera's clock); hours [from, to] (local hour of the
span's start, 0-24, wraps past midnight when from > to); place (text in the GPS place name, e.g. 'Santa Barbara');
camera (text in the camera name, e.g. 'iPhone 11'); talking (True: clips with transcript words; False: without).
count (default 12), min_score (default None), min_words (default 3: speech spans with fewer words are left out), min_gap_s (default 5.0: hits in one clip at least this far apart),
per_file (default 3 hits per clip; 0 = no limit), prefer (paths; the hit's file is the first copy under them;
default the folders settings.json 'archive_prefer' names; else the shortest path), sheet (default True: a frame
sheet of the hits, frame_height default 320 px, sheet_per_row default 6), device 'cpu' (default) or 'cuda' (waits
for the model GPU lock). Each hit: file, start, end, kind, score, meaning, words_found, text, why, detail (footage
log fields), recorded_at (local time of the span's start), place, camera, clip_length, copies, frame.

action 'status': files, clips, spans, footage hours, last update, folders in the archive; and media files under
roots (default the folders settings.json 'archive_roots' names; down to max_depth folder levels, default 4,
within time_limit_s, default 60) that are not in the archive, by folder (list_limit names each, default 50).

action 'update': add new or changed clips from the caches (nothing is transcribed or logged here; files the caches
don't know stay out). paths (default: every file the caches know), span_words (default 40), pause_s (default 1.5),
device (default 'cpu'). background (default True) runs it as an 'archive' job (letitedit_jobs shows it); False runs it
in this call. The 'index' job runs the same update for its files as its last step ('archive')."""


def run(action='search', query=None, count=None, kind=None, folder=None, exclude_folder=None, date_from=None,
        date_to=None, hours=None, place=None, camera=None, talking=None, words_weight=None, min_score=None,
        min_gap_s=None, per_file=None, prefer=None, sheet=None, frame_height=None, sheet_per_row=None, out_dir=None,
        device=None, copies=None, same_size_frac=None, min_words=None, roots=None, max_depth=None, time_limit_s=None, list_limit=None, paths=None, span_words=None,
        pause_s=None, background=True):
    if action == 'search':
        return archive.search(query, count=count, kind=kind, folder=folder, exclude_folder=exclude_folder,
                              date_from=date_from, date_to=date_to, hours=hours, place=place, camera=camera,
                              talking=talking, words_weight=words_weight, min_score=min_score, min_gap_s=min_gap_s,
                              per_file=per_file, prefer=prefer, frame_height=frame_height,
                              sheet_per_row=sheet_per_row, sheet=sheet, out_dir=out_dir, device=device,
                              copies=copies, same_size_frac=same_size_frac, min_words=min_words)
    if action == 'status':
        return archive.status(roots=roots, max_depth=max_depth, time_limit_s=time_limit_s, list_limit=list_limit)
    if action == 'update':
        args = {k: v for k, v in dict(span_words=span_words, pause_s=pause_s, device=device).items() if v is not None}
        if background:
            import letitedit.core.jobs as jobs
            inputs = dict(args)
            if paths:
                inputs['paths'] = [paths] if isinstance(paths, str) else list(paths)
            j = jobs.submit('archive', inputs, label='archive update')
            return {'job': j, 'text': f"archive update queued as job {j.get('job_id', j.get('id'))} "
                                      "(letitedit_jobs shows its progress)"}
        rep = archive.update(files=paths, **args)
        rep['text'] = (f"archive update: {rep['files_seen']} files seen, {rep['files_new_or_changed']} new or "
                       f"changed, {rep['contents_built']} clips built, {rep['contents_unchanged']} unchanged, "
                       f"{rep['spans_added']} spans added, {len(rep['errors'])} errors, {rep['seconds']} s")
        return rep
    raise ValueError("action must be 'search', 'status' or 'update'")


def register(mcp, Image):
    def _images(paths):
        out = []
        for p in paths:
            try:
                out.append(Image(data=Path(p).read_bytes(), format='jpeg'))
            except OSError:
                pass
        return out

    def letitedit_archive(action: str = 'search', query: str | None = None, count: int | None = None,
                        kind: str | None = None, folder: str | list[str] | None = None,
                        exclude_folder: str | list[str] | None = None, date_from: str | None = None,
                        date_to: str | None = None, hours: list[float] | None = None, place: str | None = None,
                        camera: str | None = None, talking: bool | None = None, words_weight: float | None = None,
                        min_score: float | None = None, min_gap_s: float | None = None, per_file: int | None = None,
                        prefer: str | list[str] | None = None, sheet: bool | None = None,
                        frame_height: int | None = None, sheet_per_row: int | None = None, out_dir: str | None = None,
                        device: str | None = None, copies: str | None = None, same_size_frac: float | None = None,
                        min_words: int | None = None, roots: str | list[str] | None = None, max_depth: int | None = None,
                        time_limit_s: float | None = None, list_limit: int | None = None,
                        paths: str | list[str] | None = None, span_words: int | None = None,
                        pause_s: float | None = None, background: bool = True) -> list:
        try:
            rep = run(action, query, count, kind, folder, exclude_folder, date_from, date_to, hours, place, camera,
                      talking, words_weight, min_score, min_gap_s, per_file, prefer, sheet, frame_height,
                      sheet_per_row, out_dir, device, copies, same_size_frac, min_words, roots, max_depth, time_limit_s, list_limit, paths, span_words,
                      pause_s, background)
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            return [{'error': f'{type(e).__name__}: {e}'}]
        imgs = _images([rep['sheet']]) if rep.get('sheet') else []
        return imgs + [rep.get('text', ''), {k: v for k, v in rep.items() if k != 'text'}]
    letitedit_archive.__doc__ = DOC
    mcp.tool(structured_output=False)(letitedit_archive)
