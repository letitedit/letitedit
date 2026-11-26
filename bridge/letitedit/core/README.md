# letitedit\core

What every job shares: where letitedit's files are, running programs, the PC render lock, background jobs, the PC's hardware, models and their environments, the cache budget, fonts for the engine.

- `cache_budget`: How much of a person's disk letitedit's redrawable work folders may hold.
- `env_build`: letitedit's model environments (torch and the voice / music engines): built on first use with uv from pinned package lists, the sizes shown before anything is downloaded.
- `first_use`: First use of a feature that needs a local model or a model environment: get what is missing.
- `font_env`: Where letitedit's engine processes load fonts from.
- `hardware`: What this PC can run locally, and which engine each letitedit feature uses.
- `jobs`: Background jobs for letitedit: long work that outlives one tool call, one AI session or a PC restart.
- `model_fetch`: Local models and data from the letitedit model manifest: what is on this PC, how big, and downloading one from its origin (the URL in its SOURCE.md record) with every file's size and SHA-256 checked.
- `render_lock`: The PC-wide one-render-at-a-time lock (Videos\render.lock by default, LETITEDIT_RENDER_LOCK overrides).
- `media`: Video and audio files through the bundled ffmpeg and ffprobe (in the install folder's app\).  (no old name: imported as `letitedit.core.media`)
- `memory_room`: Memory the PC can promise, and letitedit's idle model helpers giving it back before a heavy render.  (no old name: imported as `letitedit.core.memory_room`)
- `paths`: Where letitedit's files are: one answer for every module, whatever folder the module sits in.  (no old name: imported as `letitedit.core.paths`)
- `pipe_input`: Reading the Windows pipe a program was given on stdin without ever leaving a read waiting on it.  (no old name: imported as `letitedit.core.pipe_input`)
- `proc`: Running a program from the tools.  (no old name: imported as `letitedit.core.proc`)
- `quiet_subprocess`: Programs this code starts never open a console window, and so never take the keyboard focus.
- `store`: letitedit's small files: JSON read and written safely, a file's checksum, a path kept inside a folder, and a lock that one program holds on one file.  (no old name: imported as `letitedit.core.store`)
- `vc_runtime`: Microsoft's Visual C++ runtime (msvcp140.dll and the files that go with it) on a PC whose Windows doesn't have it.  (no old name: imported as `letitedit.core.vc_runtime`)
- `windows_trust`: Downloads check certificates the way Windows and its browsers do.  (no old name: imported as `letitedit.core.windows_trust`)

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
