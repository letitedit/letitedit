# letitedit\footage

What's in the footage: words, shots, faces, facts, search, takes and openings.

- `archive`: Footage archive: every clip letitedit has already indexed, in one local SQLite database, searchable by meaning.
- `emotion_graph`: Emotion graph of footage: mood and energy per sentence (or per shot where nobody talks), as numbers and a picture, with its turning points.
- `endings`: Does the last line of a video sound like a finished thought? Measured on the source the last clip comes from.
- `factlog`: Fact log: closed-set facts per stretch of a video, read by a local vision model, each with its measured accuracy; and a segment map that turns long clips and whole shoots into a short list of stretches that share their facts.
- `footage_notes`: Footage notes: what happens where in a source file, remembered across sessions (Claude's memory of the footage).
- `geo`: Where a clip or photo was recorded: GPS from the file's own metadata, and the nearest place offline.
- `hooks`: Hook candidates: distinct ways to open a video, proposed in about a second from what the server already knows (the cached transcripts of the cut's own source files, cached emotion graphs and picture facts when they exist, and the cut...
- `index_tools`: Search footage by what is in it, and tell people apart: model-backed tools for letitedit.
- `llm_log`: The footage log written by the agent (LLM) itself, for PCs whose footage log engine is 'llm' (see hardware.py).
- `ocr`: Offline OCR with Windows' own text recognizer (Windows.Media.Ocr; part of Windows 10/11, nothing to download).
- `perception`: what is in a source file besides talking, so the editor (an LLM) can make creative choices.
- `range_search`: Exact ranges for what you look for in footage: start and end frames, previews, stable ids (letitedit_find_ranges).
- `reference`: Reference video measuring: numbers that describe how any finished video is made (B3).
- `shot_log`: Footage log: what is seen in every shot of a video, written once by a local vision model and cached.
- `shots`: Shot boundaries that camera moves do not fool: hard cuts, punch-ins, dissolves and fades, frame-accurate.
- `speech`: Word timings for any source file, transcribed locally and cached.
- `speech_language`: The speech model on a PC with no GPU route understands English only.
- `takes`: Take finder: repeated takes of the same passage in a creator's own footage, grouped, compared and measured.
- `views`: pictures and data of footage and timelines.
- `word_reheard`: A word the transcript stretched over seconds has often swallowed other words: a restart ("without the LLM, without risking" came back as 'without' 4.9 s and 'risking' 2.2 s), so the words and times there are wrong.
- `fetch_link`: Fetch a video from a link, for "Match a video I like" and Learn only: the reference video a Look is learned from.
- `playback_copies`: Local playback-copy preparation for the editor's automatic Shotcut proxies.
- `takes_groups`: The groups of takes built, and the shapes of the result.  (no old name: imported as `letitedit.footage.takes_groups`)
- `takes_match`: Matching passages said again, the script or phrase mode, and a take compared with the reference.  (no old name: imported as `letitedit.footage.takes_match`)
- `takes_measure`: The measurements of each take (sound, picture, speech).  (no old name: imported as `letitedit.footage.takes_measure`)
- `takes_previews`: The previews: comparison sheets, clips and reels.  (no old name: imported as `letitedit.footage.takes_previews`)
- `takes_sources`: The sources: transcripts and media loaded, with the text and time helpers.  (no old name: imported as `letitedit.footage.takes_sources`)
- `takes_words`: The settings, the word lists (fillers, negations, numbers) and names.  (no old name: imported as `letitedit.footage.takes_words`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
