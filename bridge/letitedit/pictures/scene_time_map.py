"""A code scene's time map (T362): the drawing follows the cut.

A code scene is one drawing with its own clock, page time t from 0 at its start. When an edit cuts, trims or moves the
picture under it, the words it was drawn to land on come earlier or later. letitedit_timeline_apply (with the switch
scenes_follow_cut, letitedit.server.scene_follow) then gives the scene a new revision whose script opens with a time
map: page time on the new timeline -> the page time the drawing was made for. Every time written in the scene's own
script stays as it was (the drawing's own clock); the map runs before the frame function.

A map is [[p0, p1, q0, q1], ...] in page time order: a page time p in [p0, p1) draws q0 + (p - p0) * (q1 - q0) /
(p1 - p0). Before the first piece the first piece's offset holds; between two pieces and after the last the clock runs
on from where the piece before it ended (new picture under the scene, nothing drawn for it before). `map_time` here
and the script's own map do the same arithmetic. A second edit composes its map with the one already there, so the
script never carries more than one."""
from __future__ import annotations

import json
import re

START = '/* letitedit-time-map-start'
END = '/* letitedit-time-map-end */'
_BLOCK = re.compile(r'/\* letitedit-time-map-start.*?/\* letitedit-time-map-end \*/\n?', re.S)
_MAP = re.compile(r'const MAP = (\[.*?\]);', re.S)
EPS = 1e-6


def of(script):
    """The time map at the top of a scene's script, or None."""
    m = _BLOCK.search(script or '')
    if not m:
        return None
    found = _MAP.search(m.group(0))
    try:
        got = json.loads(found.group(1)) if found else None
    except ValueError:
        return None
    return [[float(x) for x in seg] for seg in got] if isinstance(got, list) and got else None


def without(script):
    """The script without its time map."""
    return _BLOCK.sub('', script or '', count=1)


def map_time(segments, t):
    """The drawing's page time for page time t (the module text)."""
    if not segments:
        return t
    k = -1
    for i, seg in enumerate(segments):
        if t >= seg[0] - EPS:
            k = i
    if k < 0:
        return t + segments[0][2] - segments[0][0]
    p0, p1, q0, q1 = segments[k]
    if t < p1 - EPS:
        return q0 + (t - p0) * (q1 - q0) / ((p1 - p0) or 1.0)
    return q1 + (t - p1)


def compose(outer, inner):
    """The map t -> inner(outer(t)): `outer` this edit's (new page time -> the page time before it), `inner` the one the
    script already has (that page time -> the drawing's own)."""
    if not inner:
        return [list(s) for s in outer]
    if not outer:
        return [list(s) for s in inner]
    cuts = set()
    for p0, p1, q0, q1 in outer:
        cuts.update((p0, p1))
        slope = (q1 - q0) / ((p1 - p0) or 1.0)
        for b in [x for seg in inner for x in seg[:2]]:     # where the inner map turns, seen from this piece
            if slope and min(q0, q1) + EPS < b < max(q0, q1) - EPS:
                cuts.add(p0 + (b - q0) / slope)
    edges = sorted(cuts)
    out = []
    for x, y in zip(edges, edges[1:]):
        if y - x < 1e-4:
            continue
        mid = (x + y) / 2
        if not any(p0 - EPS <= mid < p1 + EPS for p0, p1, _, _ in outer):
            continue                                          # between two pieces: the clock runs on, as before
        a = map_time(inner, map_time(outer, x + 1e-5))
        b = map_time(inner, map_time(outer, y - 1e-5))
        slope = (b - a) / ((y - x - 2e-5) or 1.0)
        out.append([round(x, 4), round(y, 4), round(a - 1e-5 * slope, 4), round(b + 1e-5 * slope, 4)])
    return merge(out)


def merge(segments, tol=1e-3):
    """Neighbouring pieces that are one straight line, as one."""
    out = []
    for seg in segments:
        if out:
            p0, p1, q0, q1 = out[-1]
            s0 = (q1 - q0) / ((p1 - p0) or 1.0)
            s1 = (seg[3] - seg[2]) / ((seg[1] - seg[0]) or 1.0)
            if abs(seg[0] - p1) < tol and abs(seg[2] - q1) < tol and abs(s0 - s1) < tol:
                out[-1] = [p0, seg[1], q0, seg[3]]
                continue
        out.append(list(seg))
    return out


def identity(segments, tol):
    return all(abs(q0 - p0) < tol and abs(q1 - p1) < tol for p0, p1, q0, q1 in segments or [])


def with_map(script, segments):
    """The script with `segments` as its time map at the top (any map it had replaced); without one when the map
    changes nothing."""
    body = without(script)
    if not segments or identity(segments, 1e-4):
        return body
    data = json.dumps([[round(v, 4) + 0.0 for v in seg] for seg in segments])
    shim = (f"{START} (letitedit: the drawing follows the cut. Page time t on the timeline -> the time this script was "
            "drawn for; each piece is [from, to, drawn from, drawn to]. The times below are the drawing's own.) */\n"
            "(() => {\n"
            f"  const MAP = {data};\n"
            "  const map = (t) => {\n"
            "    let k = -1;\n"
            "    for (let i = 0; i < MAP.length; i++) if (t >= MAP[i][0] - 1e-6) k = i;\n"
            "    if (k < 0) return t + MAP[0][2] - MAP[0][0];\n"
            "    const [p0, p1, q0, q1] = MAP[k];\n"
            "    if (t < p1 - 1e-6) return q0 + (t - p0) * (q1 - q0) / ((p1 - p0) || 1);\n"
            "    return q1 + (t - p1);\n"
            "  };\n"
            "  const register = M.block;\n"
            "  M.block = (name, build) => register(name, (stage, p, c) => {\n"
            "    const render = build(stage, p, c);\n"
            "    return (t) => render(Math.max(0, map(t)));\n"
            "  });\n"
            "})();\n"
            f"{END}\n")
    return shim + body
