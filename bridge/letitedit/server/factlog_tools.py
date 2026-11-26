"""MCP tools of the fact log (factlog.py): letitedit_ask_frames (one question to the local vision model over a range of a
clip) and letitedit_segments (the segment map of a clip, folder or list of files)."""
from __future__ import annotations

from pathlib import Path

import letitedit.footage.factlog as factlog

ASK_MEASURED = ('Measured on this footage (a vision test and the fact-log test): '
                'face to camera 97-100%, people count 97%, text in the picture 93%, which of 4 frames is clearest '
                '89-100%, find X among 4 frames 80-100%, cover on/off 75-100%, step label 40-67%, running vs still '
                '33-50% (a spinning fan reads as still), start/stop times 12-38%, crop fit 25-38%, level vs tilted: '
                'answered "tilted" for both.')


def ask_text(rep, path, question, choices):
    if rep.get('unavailable'):
        head = f"{Path(path).name}: \"{question}\"" + (f" (choices: {' / '.join(choices)})" if choices else '')
        when = ['photo' if Path(path).suffix.lower() in factlog.PHOTO else factlog._clock(a['t'])
                for a in rep['answers'] if a['frames']]
        return '\n'.join([head, f"Not answered: {rep['unavailable']}",
                          'The sheet holds the frames at ' + (', '.join(when) or 'no time (no frame was read)') + '.'])
    lines = [f"{Path(path).name}: \"{question}\"" + (f" (choices: {' / '.join(choices)})" if choices else ''),
             f"Answers of a small local model ({rep.get('model')}, 4-bit), each from its frame(s) alone, "
             f"{rep.get('run_s') or 0:.1f} s of GPU. {ASK_MEASURED}"]
    for a in rep['answers']:
        when = 'photo' if Path(path).suffix.lower() in factlog.PHOTO else factlog._clock(a['t'])
        ans = (a['answer'] or 'no frame').replace('\n', ' ')
        lines.append(f"{when}  " + (f"[{a['choice']}] " if choices else '') + ans[:300])
    return '\n'.join(lines)


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_ask_frames(path: str, question: str, start: float | None = None, end: float | None = None,
                           times: list[float] | None = None, choices: list[str] | None = None, frames: int = 6,
                           span_s: float = 0.0, width: int = 448) -> list:
        """Ask the local vision model (Qwen3.5-4B, 4-bit, on this PC's GPU; the same model as the fact log) one
        question about a video at several times, or about a photo. Returns a sheet of the frames, each labelled
        with its time and answer, and one line per time with the model's answer.
        path: a video or photo. times: seconds to ask at; else `frames` (default 6) times spread evenly over
        start-end (default the whole clip). span_s (default 0): 0 shows the model the one frame at each time; above
        0, three frames spread over span_s seconds around it. choices: answers to pick from (e.g. ["yes", "no"]);
        the picked one is shown in [brackets], blank when the reply named none of them. width: frame width in px
        (default 448; photos twice that).
        Each answer is a small local model's reading of those frames alone, with no context; ~1-3 s per answer
        after a ~20 s first load. Measured on this footage: face to camera 97-100%, people count 97%, text in the
        picture 93%, clearest of 4 frames 89-100%, find X among 4 frames 80-100%, cover on/off 75-100%, step label
        40-67%, running vs still 33-50% (a spinning fan reads as still), start/stop times 12-38%, crop fit
        25-38%, level vs tilted: 'tilted' for both.
        On a PC without an NVIDIA graphics card of about 4 GB (letitedit_hardware) the model is not started: the
        reply comes at once with the frames labelled by their times, no answers, and the reason."""
        try:
            rep = factlog.ask_frames(path, question, start=start, end=end, times=times, choices=choices,
                                     frames=frames, width=width, span_s=span_s)
        except FileNotFoundError as e:
            return [{'error': str(e)}]
        data = {k: v for k, v in rep.items() if k != 'sheet'}
        return [Image(data=rep['sheet'], format='jpeg'), ask_text(rep, path, question, choices), data]

    @mcp.tool(structured_output=False)
    def letitedit_segments(path: str | list[str], build: bool = False, frames_by_model: bool = True,
                         settings: dict | None = None) -> list:
        """The segment map of a clip, a folder (not searched below) or a list of files, from their fact logs
        (factlog.py), in recording order: one line per segment with its times and files, the facts that hold
        over it (each fact's measured accuracy in the legend; under 85% marked ~), moments with their times, text
        in the picture, the first words said, and the file name of a frame of it. Also the path of the text file
        with every stretch and its facts, and the folder of the segment frames.
        build (default False): False uses existing fact logs only (files without one are named); True writes the
        missing ones first (about 6 s of GPU per stretch of up to 8 s; the index job in letitedit_jobs does the same
        in the background). frames_by_model (default True): each segment's frame is the clearest of up to
        clear_n of its stretches as picked by the vision model; False: its middle stretch, without the GPU.
        settings: any of factlog.SEGMENT_DEFAULTS: gap_s 600 (recording gap that starts a segment), place_km 1.0
        (GPS move), split_keys [people, camera, hands, io, light, place] (facts whose change splits; facts under
        min_accuracy are left out), smooth_n 3, min_accuracy 0.85, topic_window_s 90, topic_min_words 12,
        topic_below 0.05 (word overlap under which the talk counts as changing subject), min_segment_s 30,
        max_segment_s 300, hold_share 0.6, clear_n 4, first_words 14."""
        try:
            m = factlog.segment_map(path, build=build, use_model=frames_by_model, **(settings or {}))
        except FileNotFoundError as e:
            return [{'error': str(e)}]
        if not m['segments']:
            if m.get('unavailable'):
                return [f"No fact log for the videos and photos here ({len(m.get('missing', []))} without one), "
                        f"and none can be built on this PC: {m['unavailable']}"]
            return [f"No fact log yet for the videos and photos here ({len(m.get('missing', []))} without one); "
                    'build=True or the index job writes it.']
        st = m['settings']
        head = [f"{len(m['files'])} files, {factlog._clock(m['footage_s'])} of video, {m['stretch_count']} stretches"
                f" -> {len(m['segments'])} segments" + (f"; no fact log yet: {len(m['missing'])} files"
                                                         if m.get('missing') else ''),
                factlog.legend(st['min_accuracy']),
                'Settings: ' + ', '.join(f'{k}={v}' for k, v in st.items()) + f"; split on: {', '.join(m['split_keys'])}",
                f"Every stretch: {m['text_file']}", f"Segment frames: {m['folder']}", '']
        return ['\n'.join(head + factlog.segment_lines(m))]
