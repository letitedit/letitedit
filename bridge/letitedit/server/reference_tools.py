"""MCP tool: measure a reference video (reference.measure)."""
from __future__ import annotations

from pathlib import Path

import letitedit.footage.reference as reference


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_measure(video: str, every_s: float = 2.0, sheet: bool = True, frames: int = 24, words: bool = True,
                        hear: bool = True, cut_above: float = 0.15, pause_s: float = 0.75, colours: int = 5,
                        refresh: bool = False) -> list:
        """Measurements of any video file, with the settings used. Cached per file content and settings.
        - duration; shots: cuts where ffmpeg's scene score passes cut_above (default 0.15), count, cuts per minute,
          median / quartile / shortest shot length, the 6 longest shots, cut times.
        - speech (words=True): Whisper transcript; words, words per minute over the whole video and over the time with
          speech, speech share (word spans joined across gaps under pause_s, default 0.75 s).
        - sound_kinds (hear=True): CLAP with the default labels, a window every every_s seconds (default 2.0, window
          length = every_s); share of windows whose highest label is speech / music / effects / other, a line per
          window, and the softmax summed per group (that sum grows with the number of labels in a group).
        - loudness: integrated LUFS, loudness range, true peak, short-term readings every every_s, louder / quieter
          stretches (checks.sound_change defaults: 4 LU apart for 3 s).
        - colour: from `frames` frames sampled evenly (default 24): average brightness (luma 0-255), saturation
          (HSV 0-255), quartiles, dominant colours (k-means, `colours` clusters, default 5) with pixel shares.
        - on_screen_text: share of sampled frames with text-like regions (OpenCV: line-shaped, high-contrast regions;
          this also counts some non-text such as grilles and stripes) and where the boxes sit on a 3x3 grid; plus the
          footage log's 'text' field when a footage log is cached for the file.
        - sheets (sheet=True): contact sheets of the sampled frames (24 per sheet) as PNG files; the first is returned.
        A part that fails reports {'error': ...} and the rest still runs."""
        try:
            rep = reference.measure(video, every_s=every_s, frames=frames, sheet=sheet, words=words, hear=hear,
                                    cut_above=cut_above, pause_s=pause_s, colours=colours, refresh=refresh)
        except (FileNotFoundError, ValueError) as e:
            return [{'error': str(e)}]
        rep = {k: v for k, v in rep.items() if k != 'per_frame'}
        if rep.get('sheets'):
            return [Image(data=Path(rep['sheets'][0]).read_bytes(), format='png'), rep]
        return [rep]

    return letitedit_measure
