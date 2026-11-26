---
name: letitedit-tools
description: Video editing tools for the user's "letitedit" editor on this PC (the `letitedit` MCP tools) - turn your own edit (ffmpeg commands, Python/JSON edit lists, EDL, OTIO) into an editable letitedit project, read and change timelines, see and hear footage, search it, and export MP4. Use when the user asks to make, edit, inspect or export a video or letitedit project.
---

# letitedit tools

The `letitedit` MCP tools (server `C:\LetItEdit\bridge\letitedit_mcp.py`, the same server and tools Claude Code uses)
work on letitedit project files (`.mlt` timelines, the format of the Shotcut engine letitedit is built on) that the
user can open and edit in the letitedit editor (`C:\LetItEdit\app`).

- `letitedit_guide` returns the index: every tool in one line and how projects work. `letitedit_guide(topic)` returns one
  tool's full description or one section (`edits`, `items`, `effects`, `code`, `python`, `import`, `engine`, `ops`).
  The tools' own short descriptions are summaries; the guide has the full text and every parameter's default.
- `letitedit_import` turns an edit written as an ffmpeg command or script, a Python or JSON edit list, an EDL or an OTIO
  file into a project; `letitedit_export_edit` writes a project back out in those forms.
- `letitedit_timeline_read` / `letitedit_timeline_apply` read and change a project by clip id (edit ops, a whole script,
  or Python `code`). When the user has the project open in letitedit, each apply is one undo step in their window,
  labelled `Codex: ...`; the project's journal records the actor as `codex`.
- `letitedit_editor` reports what the user's editor window shows now (project, unsaved changes, playhead, selection).
- Tools that make pictures return them as images in the result; most also name the saved image files in their text,
  and `letitedit_stills` / `letitedit_look` always write files. Long work (exports, index jobs) runs in the background:
  `letitedit_export` returns a job id, `letitedit_export_job(job_id, wait_s=...)` waits for it.
- Every tool is also a function of the Python module `C:\LetItEdit\bridge\letitedit_ai.py`
  (`sys.path.insert(0, r'C:\LetItEdit\bridge'); import letitedit_ai`; `letitedit_ai.tool(name, **params)` reaches any of
  them), and every picture a tool returns there is a file path in its result. Run it with the Python that runs the
  letitedit server: the `command` of the `letitedit` server in this plugin's `.codex-plugin/plugin.json` (in an
  installed copy, `C:\LetItEdit\env\Scripts\python.exe`).
- Source footage is only read; nothing is uploaded or published unless the user asks.
- The editing skills (`letitedit` first: it picks the kind of video, the stage and which skills to load) come with
  letitedit; the editor's Connect Your AI or its setup window puts them in Codex's skills folder.
