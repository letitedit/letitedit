"""MCP tool: linked versions of a project for other sizes/aspects (make, sync, list). Logic in formats.py."""
from __future__ import annotations

import letitedit.timeline.formats as formats


def versions(project, action='list', target=None, ranges=None, name=None, path=None, fps=None, reframe=None,
             focus=None, tracks=None, actor=None, dry_run=False):
    """letitedit_versions without MCP."""
    if action == 'make':
        if not target:
            raise ValueError("make needs target: 'WxH', [w, h], an aspect name or a platform profile")
        return formats.make(project, target, ranges=ranges, name=name, path=path, fps=fps, reframe=reframe,
                            focus=focus, tracks=tracks, actor=actor)
    if action == 'sync':
        return formats.sync(project, actor=actor, reframe=reframe, focus=focus, tracks=tracks, dry_run=dry_run)
    if action == 'list':
        return formats.list_versions(project)
    raise ValueError(f"action is 'make', 'sync' or 'list'; got {action!r}")


def register(mcp, Image):
    @mcp.tool()
    def letitedit_versions(project: str, action: str = 'list', target: str | list | None = None,
                         ranges: list | None = None, name: str | None = None, path: str | None = None,
                         fps: float | None = None, reframe: dict | None = None, focus: dict | None = None,
                         tracks: list | None = None, actor: str | None = None, dry_run: bool = False) -> dict:
        """Linked versions of a project at other sizes (one project, every format). A version is its own .mlt that
        opens in letitedit; its folder <version stem>.letitedit\\version.json records the main project and the main's
        file hash it came from, its ranges, which main item each of its items is, and each item's reframe.
        action='make': project = the main; target = 'WxH' (e.g. '1080x1920'), [w, h], 'vertical' | '4:5' | 'square' |
          'horizontal', or a platform profile id/name (letitedit_platforms; its export size). ranges = [[start, end],
          ...] in main-timeline seconds, in the order they play in the version [none: the whole timeline, and
          sync keeps it the whole timeline]. name: the label
          and file name '<main stem> - <name>.mlt' beside the main [the platform id or WxH]; path: another file.
          fps [the main's]. Pieces keep the main item ids (a second piece of one item gets '<id>~2'); fades at cut
          ends are left out; keyed effects are shifted to the piece. Captions are cut to the ranges; caption and text
          boxes move with the frame, text sizes x min(new w/old w, new h/old h).
          Every picture clip gets a Size, Position & Rotate effect (visible and editable in letitedit) that fills the
          new frame placed on the subject point: for each moment the first source in reframe.order with data:
          given (focus = {item id: [x, y] or [[t, x, y], ...]}, 0-1 of the picture, t in clip seconds), track
          (tracker boxes from letitedit_track: its JSON files in reframe.track_folder, or result dicts/JSON paths in
          `tracks`), action (the footage picture analysis' action point of the steady span), centre. Items with
          their own Size/Position effect keep it, moved to the new frame, and get no reframe.
          reframe settings and defaults: order ['given', 'track', 'action', 'centre'], fit 'fill' (crop to fill) |
          'fit' (whole picture, bars), zoom 1.0, key_every_s 0.5, smooth_s 1.0 (moving average), deadzone 0.03
          (fraction of the source the point moves before the frame follows), min_score 0.3 (tracker confidence),
          track_search true, track_folder <temp>\\letitedit_ai\\track, analyse false (true runs the picture analysis
          where none is cached), text_scale 'min' or a number.
          reframe mode: 'follow' [default: the one subject point above] or 'solve' (the reframing solver,
          letitedit_reframe's: several subjects kept in the crop at once - faces, motion, given boxes - on a smooth
          path, with per-item coverage and the moments where they can't share one crop in the result); its options:
          keep (rank order: 'face', 'hands' or {label, box: [x0, y0, x1, y1] 0-1, at: source s}; per main item id
          as {id: [...], '*': [...]}), priorities ({subject: required|preferred|optional|ignore}), sources
          (['face', 'action', 'track', 'aim']), platform (keep required subjects out of its covered areas), solver
          (letitedit_reframe settings: zoom [min, max], margin, calm, ...). A focus point becomes a small required box.
        action='sync': project = a version. Compares the main now with the main as the version was made/last synced
          (by item id), moves each range edge with the main-track item it was on (its start, its end or the same source moment), and applies to the version the main's changes
          inside its ranges: trims, replaced clips, effects, new and removed items, caption cues (new reframes for
          changed items). Items, cues and positions the version changed itself are kept as they are. Returns
          carried (applied), left (not applied, with why: changed in the version, outside the ranges), notes, the
          changes, and the history copy (letitedit_timeline_undo goes back). dry_run=true reports without writing.
          reframe/focus/tracks override the stored ones for the items synced.
        action='list' [default]: project = a main (its versions), a version (its own record) or a folder (every
          version in it): size, platform, ranges, made/synced times, whether the main or the version changed since,
          reframe methods.
        actor: who writes [LETITEDIT_ACTOR, else 'claude'/'codex' by the app this runs under, else 'agent']; writes hold the version's edit lease and are journaled
        in both projects' journals (make) or the version's (sync)."""
        return versions(project, action, target, ranges, name, path, fps, reframe, focus, tracks, actor, dry_run)

    return letitedit_versions
