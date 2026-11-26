"""Tool profiles: the letitedit tools one New video or Studio phase is offered (T319's rule 5; T331 step P7). Off by
default.

    enabled()                 the switch
    active()                  the profile this tool server offers: {'name', 'tools', 'extras'}, or None (every tool)
    tools_for(name, extras)   the tool names of a profile, widened by extra groups or tool names
    extras_for(request)       the extra groups a typed request or a request text calls for
    mcp_env(name, extras)     the environment a runner puts in the tool server's MCP config to start it with a profile
    note(profile)             what the guide and the server's instructions say about a profile

Every tool stays installed and in ordinary chat: a profile narrows only the MCP tools one tool server offers. Every
tool is still a function of letitedit_ai (`letitedit_ai.tool(name, **params)`), and letitedit_guide still gives every
tool's full text. A profile is the nine tools every phase shares (SHARED) plus the phase's own (PROFILES); EXTRAS are
groups a runner adds before a phase starts when the request calls for them (music written as a score, a measured
Look, made b-roll, maps, 3D, dubbing, syncing a shoot), or any tool by name.

The switch: settings.json `tool_profiles` (default true; LETITEDIT_TOOL_PROFILES, 1 or 0, wins). With it on, a tool
server started with LETITEDIT_TOOL_PROFILE=<plan | finish | review> offers that profile, widened by
LETITEDIT_TOOL_PROFILE_EXTRA (a comma list of group names and tool names). Off, or with no profile named, the server
offers every tool exactly as before. With a profile in use, letitedit_try and letitedit_check_range measure the joins
of what they render unless joins=False.
"""
from __future__ import annotations

import os
import re

SETTING = 'tool_profiles'
ENV = 'LETITEDIT_TOOL_PROFILES'
PROFILE_ENV = 'LETITEDIT_TOOL_PROFILE'
EXTRA_ENV = 'LETITEDIT_TOOL_PROFILE_EXTRA'

# every phase: the reference, long calls, the PC's state, the project's journal, the person's window and the edit
SHARED = ('letitedit_guide', 'letitedit_wait', 'letitedit_status', 'letitedit_journal', 'letitedit_instances',
          'letitedit_editor', 'letitedit_timeline_read', 'letitedit_timeline_apply', 'letitedit_timeline_undo')

# each phase's own (phases.PHASES[...]['tools'] names them)
PROFILES = {
    # phase 1: log, story, rough cut (selects, retakes, exact moments, the opening, the whole-cut check)
    'plan': ('letitedit_footage', 'letitedit_words', 'letitedit_segments', 'letitedit_find_takes',
             'letitedit_find_ranges', 'letitedit_search', 'letitedit_ask_frames', 'letitedit_looks',
             'letitedit_hooks', 'letitedit_try', 'letitedit_check_range', 'letitedit_check_frames', 'letitedit_bin',
             'letitedit_export', 'letitedit_export_job'),
    # phase 2: fine cut and finish (retiming, joins, captions, the score, shot matching, graphics, sound effects;
    # frames of the footage and the cut, caption contrast, notes on a source file, the why markers; the sound around
    # a clip edge, which the review's edge findings name)
    'finish': ('letitedit_words', 'letitedit_try', 'letitedit_check_range', 'letitedit_check_frames',
               'letitedit_check_audio', 'letitedit_timing', 'letitedit_caption_fit', 'letitedit_soundtrack',
               'letitedit_match_shots', 'letitedit_fix', 'letitedit_looks', 'letitedit_graphic', 'letitedit_assets',
               'letitedit_platforms', 'letitedit_export', 'letitedit_export_job', 'letitedit_stills',
               'letitedit_look', 'letitedit_caption_readability', 'letitedit_note', 'letitedit_bin',
               'letitedit_hear'),
    # phase 3: review and export (the review bundle, which runs the quality gate, fixes and their checks: frames of
    # the footage and the cut, caption contrast; the why markers; platform files; the sound around a clip edge)
    'review': ('letitedit_review_bundle', 'letitedit_words', 'letitedit_check_range', 'letitedit_check_frames',
               'letitedit_check_audio', 'letitedit_timing', 'letitedit_caption_fit', 'letitedit_looks',
               'letitedit_hooks', 'letitedit_platforms', 'letitedit_versions', 'letitedit_export',
               'letitedit_export_job', 'letitedit_fix', 'letitedit_soundtrack', 'letitedit_stills', 'letitedit_look',
               'letitedit_caption_readability', 'letitedit_bin', 'letitedit_hear'),
}

# groups a runner may add to any profile before a phase starts
EXTRAS = {
    'music': ('letitedit_music_write', 'letitedit_music_make', 'letitedit_song', 'letitedit_fit_music',
              'letitedit_library'),
    'learned_look': ('letitedit_look_check', 'letitedit_learn', 'letitedit_measure', 'letitedit_caption_readability'),
    'broll': ('letitedit_stock', 'letitedit_real_picture', 'letitedit_image', 'letitedit_code_scene',
              'letitedit_library', 'letitedit_my_assets'),
    'motion': ('letitedit_motion', 'letitedit_code_scene', 'letitedit_annotate', 'letitedit_object',
               'letitedit_track', 'letitedit_vfx_effects', 'letitedit_effects', 'letitedit_fonts'),
    'maps': ('letitedit_map', 'letitedit_places'),
    '3d': ('letitedit_3d',),
    'dub': ('letitedit_dub_lines', 'letitedit_dub', 'letitedit_dub_voices', 'letitedit_voice'),
    'sync': ('letitedit_sync', 'letitedit_speakers', 'letitedit_separate', 'letitedit_hear'),
    'footage': ('letitedit_transcript', 'letitedit_overview', 'letitedit_stills', 'letitedit_look',
                'letitedit_log_frames', 'letitedit_log_write', 'letitedit_note', 'letitedit_archive',
                'letitedit_library', 'letitedit_jobs', 'letitedit_hardware'),
    'formats': ('letitedit_versions', 'letitedit_reframe', 'letitedit_platforms', 'letitedit_import_srt',
                'letitedit_export_edit'),
    'critic': ('letitedit_review_bundle', 'letitedit_critic', 'letitedit_quality_gate', 'letitedit_review_note',
               'letitedit_qc'),
    'project': ('letitedit_project_new', 'letitedit_show', 'letitedit_import', 'letitedit_fetch',
                'letitedit_command_help'),
}

# the extra groups whose tools each profile's own skills name (phases.PHASES[...]['skills']): the runner adds the ones
# a request calls for (extras_for); a tool its skills name is in the profile, in one of these groups, or in another
# phase's profile (a mention of that phase's work)
WIDEN = {
    'plan': ('music', 'footage', 'sync', 'project', 'learned_look', 'broll'),
    'finish': ('music', 'motion', 'broll', 'learned_look', 'maps', 'formats', 'sync', 'footage', 'critic'),
    'review': ('music', 'learned_look', 'critic', 'footage', 'sync', 'motion', 'broll'),
}

# what a request names that calls for an extra group (a typed request's fields, or words in a request's text)
EXTRA_WORDS = {
    'music': r'\bmusic\s*[:=]\s*(?:write|written|made|ai)\b|\bwrit(?:e|ten) (?:the )?(?:music|score)\b|\bsong\b',
    'learned_look': r'\bmeasured (?:files|look|lighting|sound|visual|devices)\b|\bmine-[a-z0-9]',
    'broll': r'\bb[- _]?roll\b|cut.?aways?|\bstock\b|code.scene',
    'motion': r'\bmotion\b|animated (?:title|text)|code.scene|\barrow\b|\bannotat',
    'maps': r'\bmaps?\b|\broute\b',
    '3d': r'\b3d\b|blender',
    'dub': r'\bdub(?:bing|bed)?\b|\btranslat',
    'sync': r'\bmulti.?cam\b|\bsync\b|camera angles',
}


def _forced(name):
    forced = os.environ.get(name, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    return None


def enabled():
    forced = _forced(ENV)
    if forced is not None:
        return forced
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def _names(text):
    return [t.strip() for t in re.split(r'[,\s]+', str(text or '')) if t.strip()]


def _tool(name):
    return name if name.startswith('letitedit_') else f'letitedit_{name}'


def tools_for(name, extras=()):
    """The tool names of profile `name` (SHARED first, then its own, then the extras: group names or tool names, with
    or without 'letitedit_'), without repeats. An unknown profile name is an error."""
    if name not in PROFILES:
        raise ValueError(f"no tool profile {name!r} (profiles: {', '.join(PROFILES)})")
    import letitedit.server.tool_docs_v2 as tool_docs_v2
    out = list(SHARED) + list(PROFILES[name])
    for extra in extras or ():
        if extra not in EXTRAS and _tool(extra) not in tool_docs_v2.TOOLS:
            raise ValueError(f"{extra!r} is not an extra group ({', '.join(EXTRAS)}) or a tool name")
        out.extend(EXTRAS.get(extra) or (_tool(extra),))
    return tuple(dict.fromkeys(out))


def extras_for(request='', brief=None):
    """The extra groups a request calls for: `request` is a typed request (a dict: its values are read as text) or a
    request's text; `brief` a brief.json dict. Matching is on words (EXTRA_WORDS), case aside."""
    import json
    if isinstance(request, dict):
        request = json.dumps(request, ensure_ascii=False)
    text = str(request or '') + '\n' + (json.dumps(brief, ensure_ascii=False) if brief else '')
    return [group for group, pattern in EXTRA_WORDS.items() if re.search(pattern, text, re.I)]


def active():
    """The profile this server offers ({'name', 'tools', 'extras'}), or None: the switch off, no profile named, or an
    unknown name (said on stderr, and every tool is offered)."""
    if not enabled():
        return None
    name = os.environ.get(PROFILE_ENV, '').strip().lower()
    if not name:
        return None
    if name not in PROFILES:
        import sys
        print(f"letitedit: {PROFILE_ENV}={name!r} is not a tool profile ({', '.join(PROFILES)}); every tool is offered",
              file=sys.stderr)
        return None
    import letitedit.server.tool_docs_v2 as tool_docs_v2
    extras, unknown = [], []
    for extra in _names(os.environ.get(EXTRA_ENV)):
        (extras if extra in EXTRAS or _tool(extra) in tool_docs_v2.TOOLS else unknown).append(extra)
    if unknown:     # a server that starts beats one that refuses to: said on stderr (the MCP client's log)
        import sys
        print(f"letitedit: {EXTRA_ENV} names {', '.join(unknown)}: not an extra group or a tool, left out",
              file=sys.stderr)
    return {'name': name, 'tools': tools_for(name, extras), 'extras': extras}


def offered(tools, profile=None):
    """Of `tools` (names), the ones the server offers: all of them with no profile, else those in the profile."""
    profile = active() if profile is None else profile
    if not profile:
        return set(tools)
    return set(tools) & set(profile['tools'])


def mcp_env(name, extras=()):
    """The environment entries that start a tool server with profile `name` (for an MCP config's "env")."""
    tools_for(name, extras)       # an unknown name is an error here, not a silent full set
    env = {ENV: '1', PROFILE_ENV: name}
    if extras:
        env[EXTRA_ENV] = ','.join(extras)
    return env


def note(profile, all_tools=()):
    """What the guide's index and the server's instructions say while a profile is in use."""
    if not profile:
        return ''
    shown = [t[len('letitedit_'):] for t in profile['tools']]
    rest = sorted(t[len('letitedit_'):] for t in set(all_tools) - set(profile['tools']))
    text = (f"Tool profile '{profile['name']}': this tool server offers {len(shown)} of the letitedit tools as tools "
            f"({', '.join(shown)}).")
    if rest:
        from letitedit.core import paths
        text += (" letitedit_guide is one of them: every guide section and any tool in full come from it "
                 "(letitedit_guide('<topic>')). "
                 f"The other {len(rest)} ({', '.join(rest)}) are not offered as tools; only these are reached through "
                 f"the Python module letitedit_ai in {paths.BRIDGE_TEXT} (`import letitedit_ai; "
                 "letitedit_ai.tool('<name>', **params)`), with the same arguments.")
    return text
