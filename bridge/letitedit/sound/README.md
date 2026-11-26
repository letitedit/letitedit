# letitedit\sound

Music, songs, voices, stems, sound sync and dubbing.

- `audio_library`: The person's music and sound-effects folders, and the search letitedit_library runs over them.
- `av_tools`: Sound and picture helpers for an edit: a song fitted to the edit, recordings lined up by their sound, something followed through a shot, and picks/notes kept inside the project where a person sees them in letitedit.
- `beat_finder`: The beat finder: Beat This! (Foscarin, Schlueter & Widmer, ISMIR 2024; checkpoint final0, MIT), run on the CPU with ONNX Runtime, which every install already has.
- `guide_song`: A song the video is cut to but that is never in the upload: the person adds it in the phone app when posting.
- `media_server`: On-demand songs and stock video and photos, with a personal Pixabay key or the supporter server.
- `model_tools`: Model-backed sound tools: stems of a recording, what a stretch of sound is like, a voice saying your text.
- `music`: Music that follows the story.
- `music_gen`: Generated instrumental music on this PC (ACE-Step 1.5, MIT), lined up with a cut by the beat tools.
- `shoot_sync`: Sync a whole shoot by its sound: cameras, phones and separate audio recorders, many takes each.
- `soundtrack`: Soundtrack assembler: one song arranged around a project as a deliberate score (letitedit).
- `tonal_check`: Sustained narrow tones in sound: howls, whines, feedback, whistle-like or theremin-like leads.
- `written_music`: Music written as a score and performed in code: the tool letitedit_music_write around written-music\written-music.mjs.
- `soundtrack_arrange`: The arrangement: the skeleton of runs and fixed points, the beam search over bar slots, and the clips laid out in whole frames.  (no old name: imported as `letitedit.sound.soundtrack_arrange`)
- `soundtrack_base`: The settings and the small helpers (times, decoding).  (no old name: imported as `letitedit.sound.soundtrack_base`)
- `soundtrack_mix`: The gain envelope, the edit ops and the preview (a picture of the plan, a listen).  (no old name: imported as `letitedit.sound.soundtrack_mix`)
- `soundtrack_request`: The request typed and checked, and the project it scores.  (no old name: imported as `letitedit.sound.soundtrack_request`)
- `soundtrack_song`: The song analysed: beats, bars, sections, energy and musical events.  (no old name: imported as `letitedit.sound.soundtrack_song`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
