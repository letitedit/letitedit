"""MCP tool: platform profiles (published specs, export settings, covered areas of the frame)."""
from __future__ import annotations

from pathlib import Path

import letitedit.catalogs.platforms as platforms


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_platforms(platform: str | None = None, frame: str | None = None) -> list:
        """Published specs of YouTube, YouTube Shorts, TikTok, Instagram Reels, Instagram feed video, Facebook Reels
        and Facebook feed video (checked 2026-10-19), plus X video, Instagram and Facebook Stories and TikTok photo
        posts (2026-11-19). Every value carries its source URL, the date checked and a status: official, official-ads
        (the platform's ad specs), posting-service (a posting service's help pages, for posting through it),
        unconfirmed (best non-official source) or not documented.
        - no platform: one line per profile.
        - platform=<id or name>: the full profile (sizes, frame rates, lengths, file size, codecs, bitrates, audio,
          loudness where published, covered areas as fractions of width/height with confidence, caption facts,
          thumbnail/cover sizes, title/caption/hashtag limits) and export_settings (the export values with sources).
        - frame=<image file> with a platform: also the frame with the covered areas drawn on it, saved as a PNG."""
        if not platform:
            return [{'profiles': [p['line'] for p in platforms.list_profiles()]}]
        try:
            prof = platforms.load(platform)
        except KeyError as e:
            return [{'error': str(e).strip('"')}]
        info = {'profile': prof, 'export_settings': platforms.preset_for(prof['id'])}
        if not frame:
            return [info]
        path = platforms.safe_zone_overlay(frame, prof['id'])
        info['overlay'] = path
        return [Image(data=Path(path).read_bytes(), format='png'), info]

    return letitedit_platforms
