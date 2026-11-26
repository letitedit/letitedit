"""MCP tool: fetch a video from a link, as the reference video for "Match a video I like" and Learn (bridge/letitedit/footage/
fetch_link.py). The fetch runs inside this tool's own process tree (yt-dlp, fetched on first use, pinned and checked), so it
never needs a permission prompt in any AI. Reference videos only: no songs or sound-only fetches."""
from __future__ import annotations

import letitedit.footage.fetch_link as fetch_link

DOC = """Fetch the video behind a link, for use as a reference video (Match a video I like, letitedit_learn). One video per call (no playlist, channel or search page), on a site the downloader (yt-dlp, Unlicense) knows by name, finished videos only, no sign-in or cookies. It runs inside this tool on this PC; first use downloads the program (about 23 MB, pinned and checked), and if a fetch fails because the site changed, the newest release is fetched once, checked against its published checksum, and the fetch tried again.

action:
- reference: url, label? (a name for the saved folder), folder? (an absolute folder, instead of the default), start?, end?, seconds? (a part of the video: start and end, or start and a length in seconds; seconds or a clock time such as 1:30 or 1:02:03; up to 30 minutes long; the part is copied, so it may begin a moment before start, on a key frame). Saves the video as reference.mp4 (up to 1080p, 30 minutes, 800 MB) with record.json in <My Looks>/.imports/references/<name>/: the person's own private working files, never in the library or an installer. Returns path, the file letitedit_learn takes as a reference video, and the record: the link, title, uploader or channel, length, upload date, when it was fetched, the downloader's version, size and SHA-256, and the part fetched (section) when one was asked for.
- list: the reference videos fetched so far, each with its record.
- status: the downloader's version, where it is and whether it is on this PC.

Failures come back as ok False with reason (too_long, too_big, bad_section, playlist, live, private_or_signin, unsupported_site, not_a_video, offline, downloader_missing, failed) and an error in plain words; nothing is saved then. A whole video over 30 minutes is too_long, with duration_s, max_part_s and the video's chapters (start_s, end_s, title; empty when it has none), so a part of it can be asked for. Offline: reason offline. Nothing that was downloaded is run."""


def run(action='reference', url=None, label=None, folder=None, start=None, end=None, seconds=None):
    if action == 'reference':
        return fetch_link.fetch_reference(url, name=label, folder=folder, start=start, end=end, seconds=seconds)
    if action == 'list':
        rows = fetch_link.history()
        return {'count': len(rows), 'items': rows}
    if action == 'status':
        return fetch_link.status()
    raise ValueError("action is 'reference', 'list' or 'status'")


def register(mcp, Image):
    def letitedit_fetch(action: str = 'reference', url: str | None = None, label: str | None = None,
                        folder: str | None = None, start: str | float | None = None, end: str | float | None = None,
                        seconds: float | None = None) -> dict:
        return run(action, url, label, folder, start, end, seconds)

    letitedit_fetch.__doc__ = DOC       # before registering, so the server's letitedit_guide('letitedit_fetch') has the full text
    mcp.tool()(letitedit_fetch)
