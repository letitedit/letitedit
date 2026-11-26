"""MCP server: the letitedit tools for AI agents (Claude Code, Codex and the editor's own chat panel).

The tools work on project files and find the person's letitedit window by project themselves (live edits go through
the bridge pipe inside letitedit, \\\\.\\pipe\\letitedit-bridge). The tool set is named in toolset.txt next to bridge\\
('v2', read when the server starts; a 'without:' line leaves tools out). letitedit_guide is the index (GUIDE_V2.md).
Run: python letitedit_mcp.py   (stdio transport)
"""

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import letitedit.core.windows_trust as _windows_trust  # noqa: E402  (downloads on a clean PC: Windows checks the certificates)
_windows_trust.use()
import os
import sys
import tempfile
import time
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.server.mcpserver.utilities import func_metadata as _func_metadata  # noqa: E402
from mcp.types import CallToolResult, TextContent  # noqa: E402

_validate_arguments = _func_metadata.FuncMetadata.validate_arguments


# The same thing under the name another tool uses for it: taken when this tool has no argument of that name.
_SAME_ARGUMENT = {'start_s': ('start',), 'end_s': ('end',), 'start': ('start_s',), 'end': ('end_s',),
                  'project': ('source', 'path'), 'path': ('source', 'project'), 'source': ('project', 'path'),
                  'kind': ('kinds',)}


def _same_arguments(arguments, known):
    out = dict(arguments or {})
    for k in list(out):
        if k in known:
            continue
        name = next((n for n in _SAME_ARGUMENT.get(k, ()) if n in known and n not in out), None)
        if name:
            value = out.pop(k)
            out[name] = [value] if name == 'kinds' and isinstance(value, str) else value
    return out


def _named_arguments(self, arguments):
    """An argument the tool doesn't take is an error that names it and lists what the tool takes (instead of being
    dropped without a word). The same thing under another tool's name for it is taken (_SAME_ARGUMENT)."""
    fields = self.arg_model.model_fields
    known = set(fields) | {f.alias for f in fields.values() if f.alias}
    arguments = _same_arguments(arguments, known)
    extra = [k for k in (arguments or {}) if k not in known]
    if extra:
        import difflib
        hints = [f"{k} (did you mean {m[0]}?)" if (m := difflib.get_close_matches(k, sorted(known), 1, 0.6)) else k
                 for k in extra]
        msg = (f"unknown argument{'s' if len(extra) > 1 else ''} {', '.join(hints)}; this tool takes "
               f"{', '.join(sorted(known))}")
        raise ToolError(msg)
    return _validate_arguments(self, arguments)


_func_metadata.FuncMetadata.validate_arguments = _named_arguments

_convert_to_content = _func_metadata._convert_to_content


def _compact_content(result):
    """A tool's dict reply as compact JSON instead of the library's two-space indent, when the slimmer replies are on
    (new_video_stages.slim(), with the switch): the same values in about 84% of the characters and without a line
    break per value (measured on a New video run's 131 JSON replies). Everything else is converted as before."""
    if isinstance(result, dict):
        import letitedit.app.new_video_stages as new_video_stages
        if new_video_stages.slim():
            import pydantic_core
            return [TextContent(type='text', text=pydantic_core.to_json(result, fallback=str).decode())]
    return _convert_to_content(result)


_func_metadata._convert_to_content = _compact_content

from pathlib import Path  # noqa: E402
from letitedit.app.letitedit_client import BridgeError, BridgeUnavailable, ShotcutBridge  # noqa: E402
import letitedit.app.letitedit_instances as instances  # noqa: E402
import letitedit.server.long_calls as long_calls  # noqa: E402
import letitedit.server.toolset as _toolset  # noqa: E402

# The tool set: toolset.txt next to bridge\ names it ('v2', the only one) and may leave tools out ('without: a, b').
# LETITEDIT_TOOLS is not read; a run that sets it is told so on stderr (the MCP client's log), as is a toolset.txt
# naming a set that no longer exists.
_CHOICE, WITHOUT = _toolset.read()
TOOLSET = 'v2'
if _CHOICE not in (None, 'v2'):
    print(f"letitedit: toolset.txt names the tool set {_CHOICE!r}; the only set is 'v2', which this server offers",
          file=sys.stderr)
if (os.environ.get('LETITEDIT_TOOLS') or 'v2').strip().lower() != 'v2':
    print(f"letitedit: LETITEDIT_TOOLS={os.environ['LETITEDIT_TOOLS']!r} is not read; the tool set is named in "
          f"{_toolset.FILE} ('v2')", file=sys.stderr)
import letitedit.server.tool_docs_v2 as _tool_docs  # noqa: E402
# The tool set is one table: tool_docs_v2.TOOLS, every tool with its short text in tool_docs_v2.SHORT (and the few that
# show their full description). A tool's function comes from its family's register(mcp) below; the full description
# of any tool comes from letitedit_guide(topic).
V2_TOOLS = set(_tool_docs.TOOLS)
import letitedit.app.skill_sections as _skill_sections  # noqa: E402
# letitedit_skill (the skills by section) is offered only with its switch on (skill_sections.py; on by default)
if _skill_sections.enabled():
    V2_TOOLS.add('letitedit_skill')
import letitedit.server.tool_profiles as _tool_profiles  # noqa: E402
# A tool profile (tool_profiles.py; on by default): a New video or Studio phase's server offers only its profile's
# tools. Every tool's full text stays in LONG_DOCS for letitedit_guide, and every tool stays a letitedit_ai function.
PROFILE = _tool_profiles.active()
OFFERED = _tool_profiles.offered(V2_TOOLS, PROFILE) if PROFILE else V2_TOOLS
LONG_DOCS = {}          # tool name -> its full description (the tools show a short one; letitedit_guide(topic) gives this)


_TOOL_FAULTS = (AttributeError, TypeError, IndexError, NameError, AssertionError, ArithmeticError, RecursionError, ImportError)


def _error_text(error, limit=500):
    """An error's message as one plain line: no tool wrapper, no traceback, kept short."""
    import re
    text = str(error).strip()
    text = re.sub(r'^Error executing tool \S+:\s*', '', text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0].startswith('Traceback (most recent call last)'):
        lines = lines[-1:]
    text = ' / '.join(lines)
    text = re.sub(r'^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):\s*', '', text)
    return text[:limit] + (' ...' if len(text) > limit else '')


def _where_raised(error):
    """' at file.py:line' of the deepest frame, so a fault can be reported."""
    tb = error.__traceback__
    if tb is None:
        return ''
    while tb.tb_next:
        tb = tb.tb_next
    return f" at {Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}"


def _plain_tool_error(name, error):
    """One user-facing error policy for every MCP tool, including argument validation."""
    import re
    short = name.removeprefix('letitedit_').replace('_', ' ')
    chain, current = [], error
    while current is not None and current not in chain:
        chain.append(current)
        current = getattr(current, '__cause__', None)
    # the outermost real error: a tool that caught a deeper one says there what it means for the edit
    cause = next((e for e in chain if not isinstance(e, ToolError)), chain[-1])
    busy = next((e for e in chain if type(e).__name__ == 'Busy'), None)
    if busy is not None:        # a model job waited behind a render (render_lock.Busy): its message already says who and how long
        return str(busy)
    if "could not convert string to float:" in str(cause) and '#' in str(cause):
        return f"The {short} step found a colour code where it expected a number. Check the style values and try again."
    if hasattr(cause, 'errors'):
        problems = cause.errors()
        if problems:
            first = problems[0]
            field = '.'.join(str(piece) for piece in first.get('loc', ())) or 'an input'
            if first.get('type') == 'missing':
                return f"The {short} step needs {field}. Add it and try again."
            return f"The {short} step cannot use {field}: {first.get('msg', 'wrong value')}. Correct it and try again."
    import letitedit.core.long_paths as long_paths
    too_long = long_paths.explain(cause)
    if too_long:                # Windows only says it can't find such a file
        return f"The {short} step could not finish: {too_long}"
    if isinstance(cause, FileNotFoundError):
        where = f" ({cause.filename})" if getattr(cause, 'filename', None) else ''
        if not where and str(cause):        # our own message says which file and what to do
            return f"The {short} step cannot find a file it needs: {cause}."
        return f"The {short} step cannot find a file it needs{where}. Check the file path and try again."
    if isinstance(cause, PermissionError):
        where = f" ({cause.filename})" if getattr(cause, 'filename', None) else ''
        return f"The {short} step cannot open or save a file{where}. Close anything using it, then try again."
    if isinstance(cause, TimeoutError):
        said = _error_text(cause)
        return f"The {short} step took too long{': ' + said if said else ''}. Check Jobs for a running task, then try again."
    if isinstance(cause, (ValueError, KeyError, ToolError)):
        msg = str(cause).strip().strip("'\"")
        msg = re.sub(r'^[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception):\s*', '', msg)
        msg = msg.split('For further information visit')[0].strip()
        if msg and '\n' not in msg and len(msg) < 500 and 'Error executing tool' not in msg:
            return f"The {short} step needs a correction: {msg.rstrip('.')}. Check the inputs and try again."
    # What went wrong, in the code's own words.
    real = cause
    said = _error_text(real)
    if isinstance(real, _TOOL_FAULTS):
        return (f"The {short} step hit a fault in the tool itself, not in your inputs ({type(real).__name__}"
                f"{': ' + said if said else ''}{_where_raised(real)}). The same call will fail again: try another way, "
                f"and tell the person.")
    if said:
        return f"The {short} step could not finish: {said.rstrip('.')}."
    return f"The {short} step could not finish ({type(real).__name__}, with no message). Check its inputs and the project file."


def _plain_returned_error(name, result):
    """Some older tools return {'error': ...} as a successful result; make that a plain MCP error too."""
    import json

    data = getattr(result, 'structured_content', None)
    if not isinstance(data, dict):
        for item in getattr(result, 'content', ()):
            if not isinstance(item, TextContent):
                continue
            try:
                data = json.loads(item.text)
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                break
    if isinstance(data, dict) and isinstance(data.get('error'), str) and data['error'].strip():
        message = _plain_tool_error(name, ValueError(data['error']))
        return CallToolResult(content=[TextContent(type='text', text=message)], isError=True)
    if result.is_error:
        message = next((item.text for item in result.content if isinstance(item, TextContent)), '')
        if not message.startswith(f"The {name.removeprefix('letitedit_').replace('_', ' ')} step"):
            return CallToolResult(content=[TextContent(type='text', text=_plain_tool_error(name, ToolError(message)))],
                                  isError=True)
    return result


PICTURE_DIR = Path(tempfile.gettempdir()) / 'letitedit_ai' / 'tools'


def _save_picture(img, tool, n):
    """The file an Image is (its own path) or is saved to (PICTURE_DIR/<date-time>/<tool>-<n>.<fmt>)."""
    if getattr(img, 'path', None):
        return str(img.path)
    fmt = (getattr(img, '_format', None) or 'png').lower().replace('jpg', 'jpeg')
    d = PICTURE_DIR / time.strftime('%Y%m%d-%H%M%S')
    d.mkdir(parents=True, exist_ok=True)
    out = d / f'{tool.removeprefix("letitedit_")}-{uuid.uuid4().hex[:6]}-{n}.{"jpg" if fmt == "jpeg" else fmt}'
    out.write_bytes(img.data)
    return str(out)


def _picture_files(fn):
    """Every picture a tool returns in a list is also saved as a file; the paths come back with it: added to the
    list's last dict as 'picture_files', or as a line of text when the list has no dict."""
    import functools

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        out = fn(*args, **kwargs)
        if not isinstance(out, list):
            return out
        try:
            paths = [_save_picture(x, fn.__name__, i) for i, x in enumerate(out) if isinstance(x, Image)]
        except OSError:
            return out
        if not paths:
            return out
        for x in reversed(out):
            if isinstance(x, dict):
                x.setdefault('picture_files', paths)
                return out
        return out + ['picture files: ' + ', '.join(paths)]
    return wrapped


def _with_first_use_notes(result):
    """A download that happened inside this call (first_use.py) is said in its reply: the AI is the one talking to the person."""
    try:
        import letitedit.core.first_use as first_use
        said = first_use.drain()
        if said:
            result.content.append(TextContent(type='text', text='For the person, from this call: ' + ' '.join(x if x.endswith('.') else x + '.' for x in said)))
    except Exception:  # noqa: BLE001 - a note never breaks a call
        pass
    return result


class InstanceMCPServer(MCPServer):
    """Registers only the tools of the set (V2_TOOLS minus the ones toolset.txt leaves out), each with its short
    description; the full one is kept for letitedit_guide(topic)."""

    async def call_tool(self, name, arguments, context=None):
        # An AI with a short limit on one tool call hears "still working" before it and asks again (long_calls.py).
        # No limit set (Claude, Codex: ai_list.json says null; Codex's plugin allows 3600 s): "still working" after
        # long_calls.DEFAULT_LIMIT_S, so no call keeps the AI waiting longer.
        calls = long_calls.active()
        if calls is None:
            return await self._make_call(name, arguments, context)
        if name == long_calls.WAIT_TOOL:
            return await calls.wait(arguments)
        return await calls.call(name, arguments, lambda: self._make_call(name, arguments, context))

    async def _make_call(self, name, arguments, context=None):
        # Progress is written by the tool server so it also follows an AI running
        # outside the editor.  A broken progress file must never break an edit.
        try:
            import letitedit.app.progress_feed as progress_feed
            progress_feed.record_tool(name, arguments)
        except Exception:
            pass
        import letitedit.server.jobs_tools as jobs_tools
        call = jobs_tools.call_started(name)
        try:
            result = _plain_returned_error(name, await super().call_tool(name, arguments, context))
        except Exception as exc:  # noqa: BLE001 - errors are returned as plain tool results
            result = CallToolResult(content=[TextContent(type='text', text=_plain_tool_error(name, exc))],
                                    isError=True)
        finally:
            jobs_tools.call_ended(call)
        result = _with_first_use_notes(result)
        try:
            progress_feed.record_tool(name, arguments, finished=True, success=not result.is_error)
        except Exception:
            pass
        return result

    def tool(self, *args, **kwargs):
        decorator = super().tool(*args, **kwargs)

        def register(fn):
            if fn.__name__ in WITHOUT or fn.__name__ not in V2_TOOLS:
                return fn
            if 'letitedit_qc' in WITHOUT and fn.__doc__ and 'qc=True' in fn.__doc__:   # the export's frame check goes too
                fn.__doc__ = '\n'.join(ln for ln in fn.__doc__.splitlines() if 'qc=True' not in ln)
            import letitedit.server.tool_docs_v2 as tool_docs_v2
            LONG_DOCS[fn.__name__] = tool_docs_v2.with_project_read(fn.__name__, fn.__doc__ or '')
            if fn.__name__ not in OFFERED:      # outside this server's tool profile: in the guide, not offered
                return fn
            fn.__doc__ = tool_docs_v2.SHORT.get(fn.__name__, fn.__doc__)
            return decorator(_picture_files(fn))
        return register


V2_INSTRUCTIONS = (
    "letitedit: tools for video projects in the 'letitedit' editor on this PC. A project is a letitedit timeline "
    "file (.mlt) the person can open and edit. An edit written as an ffmpeg command or script, a Python or JSON "
    "edit list, an EDL or an OTIO file becomes a project with letitedit_import; projects are also read and changed with "
    "letitedit_timeline_read and letitedit_timeline_apply. Every tool is also a function of the Python module "
    "C:\\LetItEdit\\bridge\\letitedit_ai.py, and every picture a tool returns is also saved as a file. letitedit_guide "
    "is the index; letitedit_guide(topic) gives any tool or section in full."
)

mcp = InstanceMCPServer(name="letitedit", instructions=V2_INSTRUCTIONS + (
    _skill_sections.INSTRUCTIONS if _skill_sections.enabled() else '') + (
    ' ' + _tool_profiles.note(PROFILE, V2_TOOLS - WITHOUT) if PROFILE else ''))


def call(method: str, params: dict | None = None) -> Any:
    try:
        with ShotcutBridge() as bridge:
            return bridge.call(method, params)
    except BridgeUnavailable as exc:
        raise ToolError(f"{exc} (The project has to be open in letitedit: letitedit_show opens it.)") from exc
    except BridgeError as exc:
        raise ToolError(f"letitedit refused '{method}': {exc}") from exc


# ----------------------------------------------------------------------------- the editor windows, the guide

@mcp.tool()
def letitedit_instances() -> list[dict]:
    """List running custom editors, open projects, unsaved work and AI ownership. Read-only."""
    return instances.list_instances()


@mcp.tool()
def letitedit_wait(call_id: str, wait_s: float | None = None) -> str:
    """The result of a call that answered "still working": that call's own result, pictures included, or "still working"
    again while it runs. A call answers "still working" when it runs longer than the AI's own limit on a tool call
    allows, or than about 25 minutes for an AI without one (any long call, disk-space waits included). wait_s: how long
    to wait, at most
    the time named in the "still working" answer, which is also the default. Results are kept for 30 minutes after a call
    finishes, until the tool server restarts. Repeating the original call while it runs gives the same answer and starts nothing new."""
    return 'letitedit_wait collects a background call by its call_id.'


@mcp.tool()
def letitedit_guide(topic: str | None = None) -> str:
    """One-page reference: every letitedit tool, edit command, clip type, effect form and transition, and how the
    engine behaves."""
    import letitedit.server.guide_v2 as guide_v2
    text = guide_v2.text(topic, LONG_DOCS, WITHOUT)
    if PROFILE:     # a tool profile in use: the index, and a tool outside it, say what this server offers
        name = 'letitedit_' + str(topic or '').strip().lower().removeprefix('letitedit_')
        if not topic or (name in LONG_DOCS and name not in OFFERED):
            text = _tool_profiles.note(PROFILE, V2_TOOLS - WITHOUT) + '\n\n' + text
    return text


@mcp.tool()
def letitedit_import_srt(srt: str | None = None, path: str | None = None,
                       track_name: str = "Subtitles", lang: str = "eng") -> dict:
    """Load captions into a caption track of the project open in letitedit from SRT text or an .srt file (times are
    timeline times): a new track named track_name, or its items overwritten where they overlap; lang is a 3-letter
    code. The import is one undo step in the window. The track's captions are drawn on the video once it has a
    caption look: {op: captions, track, burn_in: true, style} with letitedit_timeline_apply, or the app's caption
    looks."""
    if not srt and not path:
        raise ToolError("Give srt text or a path to an .srt file.")
    params: dict[str, Any] = {"track_name": track_name, "lang": lang}
    if srt:
        params["srt"] = srt
    else:
        params["path"] = path
    return call("import_srt", params)


# Fast, truthful checks rendered by melt (frames, ranges, audio, QC) and crash-proof chunked exports.
from letitedit.server.check_tools import register as register_checks  # noqa: E402
register_checks(mcp, Image)

# Edit scripts: read a timeline as text with stable clip ids, change it by id, word-level tighten, undo.
from letitedit.server.timeline_tools import register as register_timeline  # noqa: E402
register_timeline(mcp, Image)

# Fonts, styles and Python graphics: choose and preview; placing them is a timeline edit.
from letitedit.server.kit_tools import register as register_kit  # noqa: E402
register_kit(mcp, Image)

# Footage, new projects, showing a project to the user, music/SFX library.
from letitedit.server.core_tools import register as register_core  # noqa: E402
register_core(mcp, Image)

# Importing the agent's own edit, exporting it back, views, scratch versions, music fitting, sync, tracking, shared
# markers and bin, sound separation and description, search, speakers, voice.
from letitedit.server.v2_tools import register as register_v2  # noqa: E402
register_v2(mcp, Image)

# Background jobs (index footage, the footage log) and the PC render lock: what the PC is doing for letitedit.
from letitedit.server.jobs_tools import register as register_jobs  # noqa: E402
register_jobs(mcp, Image)

# The project journal (who changed what), the edit lease and track owners.
from letitedit.server.journal_tools import register as register_journal  # noqa: E402
register_journal(mcp, Image)

# Platform profiles: facts per platform (sizes, lengths, covered areas, limits) with sources.
from letitedit.server.platforms_tools import register as register_platforms  # noqa: E402
register_platforms(mcp, Image)

# The PC's hardware tier and the footage log written by the agent itself (no capable GPU, or by choice).
from letitedit.server.hardware_tools import register as register_hardware  # noqa: E402
register_hardware(mcp, Image)

# Measuring any video's style (shots, speech, sound, colour, text).
from letitedit.server.reference_tools import register as register_reference  # noqa: E402
register_reference(mcp, Image)
# One export reviewed end to end (every part, the brief, the checks, the critic) and one delivery verdict.
from letitedit.server.review_tools import register as register_review  # noqa: E402
register_review(mcp, Image)
from letitedit.server.geo_tools import register as register_geo  # noqa: E402
register_geo(mcp, Image)

# Linked versions of a project at other sizes (one project, every format).
from letitedit.server.formats_tools import register as register_formats  # noqa: E402
register_formats(mcp, Image)

# Every indexed clip on this PC in one local database, searched by meaning.
from letitedit.server.archive_tools import register as register_archive  # noqa: E402
register_archive(mcp, Image)

# What the editor window shows now (playhead, selection, words there): for editing by talking.
from letitedit.server.editor_tools import register as register_editor  # noqa: E402
register_editor(mcp, Image)

# Fix-in-post: repaired copies (night, shake, punch-in, voice) applied as a visible effect on a clip.
from letitedit.server.fix_tools import register as register_fix  # noqa: E402
register_fix(mcp, Image)

# Generated 3D clips of a model (Blender, headless) and maps drawn from clips' GPS (offline data).
from letitedit.server.render3d_tools import register as register_3d  # noqa: E402
register_3d(mcp, Image)
from letitedit.server.maps_tools import register as register_map  # noqa: E402
register_map(mcp, Image)

# Motion clips (animated titles, lower thirds, kinetic text, count-ups, charts, end cards) rendered by HyperFrames.
from letitedit.server.motion_tools import register as register_motion  # noqa: E402
register_motion(mcp, Image)
from letitedit.pictures.code_scenes import register as register_code_scenes  # noqa: E402
register_code_scenes(mcp, Image)
from letitedit.pictures.image_gen import register as register_image  # noqa: E402
from letitedit.sound.media_server import register as register_stock  # noqa: E402
register_image(mcp, Image)
register_stock(mcp)
# Real pictures of named things (logos, people, places, books...) from open sources, fetched beside the project (T173).
from letitedit.server.real_picture_tools import register as register_real_picture  # noqa: E402
register_real_picture(mcp, Image)
# A video, or only its sound, from a link: a reference for a Look, a song to cut to (T177).
from letitedit.server.fetch_tools import register as register_fetch  # noqa: E402
register_fetch(mcp, Image)
from letitedit.server.object_tools import register as register_object  # noqa: E402
register_object(mcp, Image)

# Instrumental music written on this PC and cut to the edit on its beats.
from letitedit.server.music_gen_tools import register as register_music_make  # noqa: E402
register_music_make(mcp, Image)

# Music written as a score and performed in code, on any PC (T73).
from letitedit.sound.written_music import register as register_music_write  # noqa: E402
register_music_write(mcp, Image)

# The fact log's segment map and one question to the local vision model about frames.
from letitedit.server.factlog_tools import register as register_factlog  # noqa: E402
register_factlog(mcp, Image)

# Repeated takes of one passage (retakes, false starts, restarts inside a line), compared and measured side by side.
from letitedit.server.takes_tools import register as register_takes  # noqa: E402
register_takes(mcp, Image)

# Shot matching: exposure, white balance and gentle tone toward a reference clip, as editable Color Grading effects.
from letitedit.server.shot_match_tools import register as register_shot_match  # noqa: E402
register_shot_match(mcp, Image)

# Pointing at something in a clip (ring, arrow, box, label, magnifier, freeze, tracked) from its own source picture.
from letitedit.server.annotate_tools import register as register_annotate  # noqa: E402
register_annotate(mcp, Image)

# A deliberate score from one song: sections, hits on musical events, protected natural sound, the mix measured.
from letitedit.server.soundtrack_tools import register as register_soundtrack  # noqa: E402
register_soundtrack(mcp, Image)

# Caption layout: line breaks, grouping, size and place of captions against faces, other text and platform overlays.
from letitedit.server.caption_layout_tools import register as register_caption_fit  # noqa: E402
register_caption_fit(mcp, Image)

# Exact ranges of described moments (picture first, so silent actions too), with stable ids; camera moves are not cuts.
from letitedit.server.range_search_tools import register as register_find_ranges  # noqa: E402
register_find_ranges(mcp, Image)

# Reframing to another shape that keeps several subjects in frame (faces, hands, the part shown), with split/inset offers.
from letitedit.server.reframe_tools import register as register_reframe  # noqa: E402
register_reframe(mcp, Image)

# Timing, motion and rhythm of an edit or a video (one tool, one view per question: map, slow, cuts, speech, joins, sync, trajectory, meaning).
from letitedit.server.timing_tools import register as register_timing  # noqa: E402
register_timing(mcp, Image)

# The asset library: emoji, icons, stickers, graphics, transitions, sound effects and music, with licences.
from letitedit.server.assets_tools import register as register_assets  # noqa: E402
register_assets(mcp, Image)
from letitedit.server.my_assets_tools import register as register_my_assets  # noqa: E402
register_my_assets(mcp, Image)

from letitedit.server.learned_looks_tools import register as register_learned_looks
register_learned_looks(mcp, Image)

# The app's How to reference (AI > How to / Command Finder), searched without an editor window.
from letitedit.server.command_help import register as register_command_help  # noqa: E402
register_command_help(mcp, Image)

# Dubbing a project into another language: lines to translate, the translated lines voiced on this PC.
from letitedit.server.dub_tools import register as register_dub  # noqa: E402
register_dub(mcp, Image)



@mcp.tool()
def letitedit_skill(index: list[str] | None = None, sections: list[str] | None = None) -> str:
    """The letitedit skills by section. index: skill names (letitedit-fine, ...): each skill's description and its
    sections, one line each (`<skill>#<id>  its job  (~tokens)`). sections: `<skill>#<id>` for a section (an id with
    parts, such as `letitedit-firstcut#1a`, gives all of them) or `<skill>` for the whole skill: their text, word for
    word as in the skill, in the skill's order. Both in one call give the index first."""
    parts = []
    if index:
        parts.append(_skill_sections.index(index))
    if sections:
        parts.append(_skill_sections.read(sections))
    if not parts:
        return 'The skills: ' + ', '.join(_skill_sections.names())
    return '\n\n'.join(parts)


if __name__ == "__main__":
    os.environ['LETITEDIT_TOOL_SERVER_PID'] = str(os.getpid())  # model workers end when this server does
    mcp.run("stdio")
