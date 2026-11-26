# letitedit

The editing engine for AI-made videos: a custom build of the Shotcut editor (now letitedit) plus a tool server that Claude, Codex
or the editor's own chat panel use to see footage, edit projects, check and export. One LLM subscription plus free
local models is all it needs. This file sums up what it is today (29 Oct 2026: the app lives in `C:\LetItEdit`, renamed
in full, with the letitedit look; `BACKLOG-HISTORY.md` "The letitedit app: moved out of ShotcutDev" has the details); the detailed build log is
`ROADMAP-PROGRAM.md`. What this file said before 11 Nov (dated feature notes with their task numbers):
`dev-history\guides-before-t192-2026-11-11.md`.

## The pieces
| Piece | Where | Notes |
|---|---|---|
| Editor "letitedit" | `app\` (the exe the launcher opens is named in `app\ai-assist-executable.txt`, set by `build.ps1 -Promote`; newer staged `letitedit-YYYYMMDD.N.exe` builds sit beside it) | Fork of Shotcut 26.9.27 (source `src\`, letitedit's own code mostly in `src\src\letitedit\`). Loads its own font library (bold is drawn through each font's style name, see the export engine row), AI chat panel with push-to-talk (the "Hold to talk" key, F12 by default), live edits as one undo step. Settings in `appdata\`. |
| Export engine | `app\melt.exe`, `app\lib\mlt\` | MLT 7.41.0 with two modules rebuilt from letitedit's patches (`engine-patches\README.md`): the text module loads letitedit's font library and draws the weight asked, the plus module draws a caption that runs to the video's end or across an export chunk. Only module files that passed `engine-patches\check_engine.py` (`modules\VERIFIED.txt`) deploy or ship: `engine-patches\deploy.ps1` (and every editor build) swaps them in when no letitedit window has them loaded; the installer ships them. The patched modules are the ones in `app\lib\mlt\` on this PC (their SHA-256 matches `modules\SHA256SUMS.txt`, 11 Nov). |
| Tool server (MCP) | `bridge\letitedit_mcp.py` | 89 tools in the one tool set (`letitedit_skill` while `skill_sections` is on, the default; `toolset.txt`; `letitedit_guide` lists them, `letitedit_qc` is left out); also a Python module `bridge\letitedit_ai.py`. Registered for Claude Code (user `letitedit` server) and Codex (plugin `letitedit@letitedit-local`). |
| The AIs | `bridge\ai_list.json` (the one list: how to find, start and sign in each AI, its models, what it can do, its limit on a tool call), read by `bridge\ai_clis.py` and the editor | Claude Code and Codex run as their own programs; for anyone who hasn't chosen, Claude Opus 5.5 at medium or Codex GPT-6.1-Sol at medium (`ai_clis.DEFAULT_CHOICE`). A connector AI (Antigravity) runs in chat bubbles through `bridge\acp_host.py`, downloaded on demand into its own folder with a private sign-in; nothing of it runs hidden. |
| Guide | `GUIDE_V2.md` (built by `tools\build_guide_v2.py` from `GUIDE.md` sections + `bridge\tool_docs_v2.py`) | What `letitedit_guide` returns. |
| Settings | `settings.json` | Hardware tier choices, footage-log engine, model downloads (auto/ask). |
| Local models | `models\`, `vfx\models\` (each with SOURCE.md) | Speech (whisper), vision (Qwen3.5-4B on 8 GB graphics cards, 2B on 4 GB), voices (dots-tts default), music (ACE-Step 1.5), fix-in-post, embeddings, maps data in `maps\`. |
| Background jobs | `jobs\`, worker `bridge\start_jobs_worker.ps1` | Indexing, long renders; `letitedit_status`, `letitedit_jobs`. The scheduled task "letitedit job worker" starts it at sign-in and resumes interrupted jobs (the old "Shotcut AI job worker" task is disabled). |
| Installer | `release\installer\out\letitedit-Setup-1.0.0-<build>.exe`; the newest is 20261110.2 (557 MB; sandbox-installed 10 Nov, 103 of 103 checks; not code-signed, never tried on a second PC, not published) | Installs to any folder, builds its Python environment, fetches models on first use, first-run setup for Claude/Codex (tools, plugin and the editing skills). Ships the editor, the tools, skills, the library styles and Looks, the asset library, fonts, the Codex plugin and the motion-clip engine with its own Node; it draws with the PC's own Edge or Chrome, and motion items are drawn as graphics where it can't. |
| Shared Looks | `tools\shared_looks\` (the Worker at looks.letitedit.app, `pull.py`) | Learned Looks people share (settings and recipe only) arrive in the git-ignored `shared-looks-inbox\`, as untrusted data. |
| Problem reports, update check | `tools\problem_reports\` (the reports Worker at reports.letitedit.app, deployed 24 Nov; `standin.py` for tests; `pull.py`); the editor's `letitedit\dialogs\problemreport.*` and `updatecheck.*` (T368) | Help > Report a problem..., a button on two error screens, a crash report offered at the next start and a setup problem's report: the person sees and edits every part, nothing goes without Send, paths, names and keys are cleaned out. A daily check of one small file for a newer build (a note and a link, never a download). The editor's two addresses (`https://reports.letitedit.app`, `https://letitedit.app/latest.json`) are set from the next build; only the person's own window uses them (`tests\t368\REPORT.md`). |
| Licences | `THIRD-PARTY-NOTICES.md`, `LICENSES-REVIEW.md`, `release\source\` | GPL source prepared locally, not published. |
| Tool code | `bridge\letitedit\<job>\` (core, catalogs, sound, pictures, footage, timing, review, looks, app, server, timeline) | Every module also answers to its old name in `bridge\` (a small alias file: one module object under both names), so the names in this table and `python bridge\<name>.py` still work; inside the package only the real names are used (`IMPORTS.md` in each job folder, enforced by a test). The biggest modules are in parts beside them (`<module>_<part>.py`), every name imported back; `CODEMAP.md` lists them all. Where Styles, Looks and Themes come from: `letitedit.looks.catalog`. |
| Tests | `bridge\tests\<job>\test_*.py` (325 files, about 3,300 tests; some are pytest-style), fixtures in `tests\fixtures\` | `python tools\run_tests.py fast` (215 files) or `slow` (88); each file takes its own PC-lock ticket when it renders (`AGENTS.md`, "Building, testing, shipping"). |

## What the LLM can do with it (the tools, by job)
- **Understand footage:** footage scan (sound, picture, faces, places from GPS), transcripts, the fact log (people,
  faces, facing camera, text, moments, each with its measured accuracy) and the segment map (an hour as tens of
  lines), one question to the vision model about any frames, search by look/sound/words, speakers, archive search
  across everything indexed, reference-video measuring, a reference video fetched from a link (`letitedit_fetch`).
- **Cut to a song, upload without it:** `letitedit_song`: a song on the track 'Song (not in the export)', which no export
  includes; its beats for the picture, the upload measured against it, a preview with it, and the facts for adding it in
  the phone app.
- **Edit:** read/apply/undo a project as an edit script (any engine effect, keyframes, transitions, ffmpeg graphs,
  Python graphics, .ass text), import its own edit (ffmpeg, Python/JSON, EDL, OTIO) and export it back, try versions
  side by side, linked versions for every platform with reframing, a camera-switched cut of synced angles of one talk
  (`{op: multicam}`), journal/edit lease/track owners for several agents.
- **Make:** fix-in-post (night, shake, punch-in, voice), generated 3D shots (Blender), maps, music, cloned voice
  (dots-tts), music fitted to beats, sound separation, stock video and photos (`letitedit_stock`), real
  pictures of named things (`letitedit_real_picture`), an object lifted out of its shot (`letitedit_object`, `{op: lift}`),
  code scenes. **Written music:** `letitedit_music_write` and `written-music\`: the AI writes every note as JSON for that
  exact cut, one bundled file performs it on any PC with no GPU, download or network; written or real music is the AI's
  own call per video (the owner, 4 Nov), with the library, ACE-Step and a person's own files as the real-music side. The
  installer carries 32 public-domain songs (`starter-music`); `letitedit_library` finds them by feeling, tempo and length.
- **Looks:** New video's Looks are in `looks\manifest.json` (`LOOK-SETTINGS.md`), with the boxes each asks for
  (required, strongly recommended or optional; answers kept beside the video in `inputs.json`), so a Look with other
  boxes needs no editor build. Learned Looks (`letitedit_learn`, `letitedit_look_check`, the `letitedit-learn` skill) are
  the person's own, in `Documents\letitedit\My Looks`. Code scenes can use optional drawing kits (`M.look.<name>`,
  listed by `letitedit_motion(action='hands')`; based on anidoodle, Apache-2.0); a scene in a look of its own stays a
  full choice.
- **My assets:** the person's own logo, intro, outro, colours, clips, sounds, pictures and fonts in one folder that works
  on every video (`Documents\letitedit\My assets`, or `my_assets_dir` in settings.json); `letitedit_my_assets` lists
  them with measured facts and the person's note; `mine:<id>` is accepted by `letitedit_assets`, styles, pop-ups and
  graphics, with licence `own` and no credit line. It's the person's organising space, no promise that a video will use
  it and no requirement that it does (the owner, 4 Nov), so the skills say nothing either way. Their files are only read.
  The app's panel is File > My Assets...; the review bundle lists which items the video uses (`my-assets.json`).
- **Check and finish:** frames as the export renders them (with platform covered areas), ranges, loudness, overview
  sheets, caption readability, crash-proof exports with platform settings and loudness finishing.
- **Talk to the editor:** what the editor shows now (playhead, selection, words) for Claude/Codex voice modes;
  push-to-talk in the chat panel.

## The app's AI features and what they run

- **New video** (`src\src\letitedit\newvideo\`): five steps, Format (Short or YouTube), Content (the person's clips,
  or 100% AI), Look (Style tabs worked out from the clips by `what_was_filmed`; the Looks of `looks\manifest.json`, the
  person's learned Looks under every tab they fit, Match a video I like, Freestyle, Edit with the AI myself), Theme and
  Go (music). It sends the request to the chat; the AI makes the first cut with the `letitedit` and
  `letitedit-firstcut` skills. Clips that are several cameras on one talk get `{op: multicam}` in the request.
  New video's and Learn's own chat starts Claude Code with only letitedit's tool server (`--strict-mcp-config`,
  `src\src\letitedit\chat\newvideotools.h`; on the src branch `t3/t240-new-video-own-tools`, not in a build yet):
  none of the person's other MCP servers or claude.ai connectors, on every turn of that chat; their skills are as
  ever. Codex and connector AIs start as before.
- **Learn from a video** (Home, or Match a video I like): `letitedit_learn` with the `letitedit-learn` skill makes a
  personal Look in `My Looks`; there is no name to type (the AI names it), and a Look's card has Rename. Learned
  Looks are shared with letitedit.app in the background unless turned off in Settings > Share learned Looks...
  (`letitedit.looks.look_share`; in the editor source and staged builds since 20261111.11, not yet in the promoted one).
- **Opening panel, New hook**: `bridge\hooks.py next | more | mark | request | preview | apply --from-app` over the
  video's `hooks.json` (in the `<video>.letitedit` folder beside it).
- **My Looks panel**: `bridge\look_library.py --request` reads/copies/updates Learn's personal revisions; "Use on this video" selects the project's Look. Import a style is now the existing Learn from a video flow, using the retained measurement detectors.
- **Live Review** (the switch in Review, off by default): the person watches, talks and draws; the AI takes the notes
  one at a time on a copy (`src\src\letitedit\review\livereview.cpp`, `bridge\live_review.py`, `letitedit_review_note`)
  and they land one Undo step each when nothing plays. Details: `tests/t53/REPORT.md`.
- **Click the thing in the video** (`src\src\letitedit\player\previewobjects.cpp`, `VuiBase.qml`): a click in the
  player selects the topmost item and pauses; the timeline selects the same clip; a typed or spoken AI request carries
  its id, time and the project's revision. The inspector isn't built. Details: `tests/t99/REPORT.md`.
- **Review** (Ctrl+Shift+R): full-screen player, draw on frames, typed or spoken notes; submitting sends them to the
  AI, which keeps the old version and makes each change as one undo step.
- **Ask the AI** (the chat panel: the person's own Claude Code or Codex in the background, with their normal tools and
  MCP servers plus letitedit's (New video's and Learn's own chat: letitedit's only, above); permission requests
  answered in the panel; a starred default model, Opus or GPT-6.1-Sol at medium effort by default (11 Nov;
  `ai_clis.DEFAULT_CHOICE`); chats kept per project and resumed after a restart; messages can be sent while the AI
  works), push-to-talk (`bridge\voice_chat.py`), **timeline on/off**
  (AI-live editing).
- **Reply speed** is in the model menu (also New video): per-AI Normal/Fast choices, per-run only, with model/plan limits and a visible Normal fallback; Claude Fast uses paid credits outside the plan. It is not Turbo (`tests/t228/REPORT.md`).
- **Antigravity**: Google's connector, downloaded on demand and pinned in `bridge\ai_antigravity.py`, with a private
  sign-in; only ever a conversation on screen (what it may do without asking: the top of `bridge\acp_host.py`). Its
  tool calls end at 3 minutes, so it gets "still working" and `letitedit_wait` (`bridge\long_calls.py`).
- **Connect Your AI**: registers the tools in Claude Code and Codex and runs `skills\install.py`, for the AIs on this
  PC. Its tick box (`background_jobs` in `panel.json`, on by default) turns off AI runs nobody watches: the critic
  becomes a visible second conversation in the panel, New hook refill and the emotion graph stay out.
  `bridge\ai_clis.py` finds the programs. Choosing Codex there sticks (a refresh used to put Claude back; fixed in the
  editor source, staged since 20261111.11).
- **How to / Command Finder**: `command-reference.json`, the same text `letitedit_command_help(query)` searches.

## Rules it keeps
Tools state facts and options; the LLM makes every creative call. One subscription plus free local models.
Originals are only read. Generated pictures and sound are labelled as generated. Nothing of the person's videos is
uploaded (learned Looks' settings and recipes are shared with letitedit unless turned off).

## History in short
- **Late Sep - early Oct:** custom build with a control channel for agents; episode tools.
- **8 Oct:** LLM-first upgrade: fast checks, crash-proof exports, the edit script, fonts, graphics, kits, music,
  footage notes, the 20-tool core and one-page guide, chat panel, the "paintbrush" (any effect, keyframes, ffmpeg).
- **9-14 Oct:** redesign (import your own edit, views, services), footage log, loop-2 A/B tests (letitedit vs
  stock Claude; 7 of 22 pairs won so far).
- **19-20 Oct:** roadmap A1-C6: job runner and render lock, Codex parity, hardware tiers, fonts/bold, installer,
  journal and edit lease, licences, GPS places, archive search, reference measuring, platform profiles, one project
  every format, fix-in-post, thumbnails, 3D/maps/music/voice, editing by talking.
- **20 Oct (late):** vision model limited to facts it gets right (fact log + segment map + ask-the-frames), from a
  study of 44 A/B runs and a 75-question accuracy test.
- **Late Oct - Nov:** renamed letitedit (26 Oct); New video, Styles, Looks and Themes; learned Looks; the installer
  and the site (`PROJECT-STATE.md`, `BACKLOG-HISTORY.md`).

## Known gaps
In the October A/B tests story and pacing lost to stock Claude (it won on captions and sound). Learned Looks don't
yet look like their references (around 5/10). Vision facts under 85% (place, subject, indoors/outdoors) are marked
`~`. Fix-in-post: stabilising and voice gains are small. Music mood control is weak. Maps have no street-level data.
Real microphone push-to-talk is untested. The installer isn't code-signed and hasn't been tried on a second PC.
