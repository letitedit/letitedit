"""MCP tool letitedit_object: an object cut out of a shot, as a layer. The work is in object_layer.py and object_lift.py."""
from __future__ import annotations

from pathlib import Path


def _resolve(project, clip, at, start, end):
    """A clip and its own seconds; with a project and no clip, the footage on the main picture at those timeline times."""
    if clip:
        return clip, at, start, end, None
    if not project:
        raise ValueError('Say which footage: clip (a file) with its own seconds, or project with timeline seconds.')
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout, main_track, to_seconds
    script = es.read(es._resolve(project))
    main = main_track(script)
    moment = at if at is not None else start
    if moment is None:
        raise ValueError('Say which moment: at, or start and end.')
    for item, s, e in layout(main) if main else []:
        if item.get('clip') and s - 1e-6 <= float(moment) < e:
            base = to_seconds(item.get('in') or 0)
            speed = float(item.get('speed') or 1.0)
            to_src = lambda t: None if t is None else round(base + (float(t) - s) * speed, 4)
            return item['clip'], to_src(at), to_src(start), to_src(end), {'item': item.get('id'), 'on_timeline': round(s, 4)}
    raise ValueError(f'There is no footage on the main picture at {float(moment):.2f} s of that project.')


def run(action='frame', clip=None, project=None, at=None, start=None, end=None, this=None, not_this=None, in_front=None,
        object=None, move=None, drop=None, add=None, points=None):
    import letitedit.pictures.object_layer as ol
    if action in ('frame', 'try', 'make'):
        clip, at, start, end, where = _resolve(project, clip, at, start, end)
    else:
        where = None
    if action == 'frame':
        out = ol.frame_sheet(clip, at, start, end)
    elif action == 'try':
        if at is None:
            raise ValueError('try needs at: the moment of the frame the points are on')
        out = ol.try_points(clip, at, this, not_this, in_front)
    elif action == 'make':
        if start is None or end is None or at is None:
            raise ValueError('make needs start, end (the stretch the layer can be used in) and at (the frame the points are on)')
        out = ol.make(clip, start, end, at, this, not_this, in_front)
    elif action == 'outline':
        if not object:
            raise ValueError('outline needs object: an id from make')
        out = ol.edit_outline(object, move, drop, add, points)
    elif action == 'info':
        if not object:
            raise ValueError('info needs object: an id from make')
        meta = ol.load(object)
        out = ol._reply(meta, [str(ol.folder_of(object) / 'cutout.jpg'), str(ol.folder_of(object) / 'outline.jpg')])
    else:
        raise ValueError(f'action is frame | try | make | outline | info, not {action!r}')
    if where:
        out['source'] = clip
        out['footage'] = where
    return out


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_object(action: str = 'frame', clip: str | None = None, project: str | None = None, at: float | None = None,
                         start: float | None = None, end: float | None = None, this: list | None = None, not_this: list | None = None,
                         in_front: list | None = None, object: str | None = None, move: dict | None = None, drop: list | None = None,
                         add: list | None = None, points: list | None = None) -> list:
        """One object out of a shot, as a layer: a tool, a part, a product, a mug. Runs on this PC (SAM 2 and BiRefNet on the GPU, LaMa).

action='frame': a sharp frame near `at` (or in start..end), with a grid in the clip's own pixels, to choose points on.
action='try': what SAM 2 finds on the frame at `at` from this (points on the object) and not_this (points on what touches it or
  looks like it), and in_front (points on a hand or anything else that passes in front of it). One or two seconds; the picture shows
  the mask in pink, what's in front in green, your points, and a close-up with a grid. area_share, box, pieces and touches_frame_edge are
  in the reply. Shiny or same-coloured surroundings need not_this points.
action='make': follows it through start..end (the stretch the layer can be used in) from the frame at `at`, tracks it as one rigid thing,
  lines up about 60 frames into a clean picture of it at twice the size (the plate), and makes one outline there, which the track
  carries through the shot. Reply: `object` (the id), `outline_points` as [number, x, y] in plate pixels, `checks`, `clear` (the stretches where
  nothing is in front of it), `axis_deg` (how far it leans), and two pictures: the cut-out on dark and bright, and the numbered outline on
  the plate with a grid. About 15 s of work per second of footage, more with in_front.
  **It refuses rather than making a bad layer:** {made: false, why: ...} when the object bends or moves in parts (a cable, a cloth, a plant, a
  door opening), turns to show another side, leaves the frame, is covered, or blurs for too long; `checks.holds` is the range that would work,
  when there is one. Nothing else in this tool works per frame.
action='outline': object, with move {number: [x, y]}, drop [numbers], add [[after_number, x, y]], or points [[x, y]...] for the whole outline, in plate
  pixels. The curve runs through the points and each stretch settles on the nearest clear edge within a few pixels; points where it turns sharply stay
  corners. A new object id, with its two pictures; the old id stays.
action='info': an object's details and pictures again.
clip with its own seconds; or project with timeline seconds (the footage on the main picture there; the reply's `source` names the file).

Using it (letitedit_timeline_apply):
  {op: lift, object, from, to}: it comes out of the shot, holds and goes back, moves as keys on its own track, a filled-in still of the frame on a track
  below it for the background to go away. letitedit_guide('lift') has its fields.
  {vfx: {effect: object, source: {clip, in, out}, params: {object, show}}} on an upper track: where it is in the shot. show: object (anything on a
  track below it goes behind it) | outline | glow | recolour, with color.
Limits: rigid things that show one side. One object per id. Footage with a speed change can't be lifted. A hand over it during the hold is painted out from the
plate; the object on the plate is what shows, so a part it never showed uncovered stays as the hand left it."""
        try:
            out = run(action, clip, project, at, start, end, this, not_this, in_front, object, move, drop, add, points)
        except ValueError as ex:
            return [{'error': str(ex)}]
        pictures = out.pop('pictures', [])
        images = [Image(data=Path(p).read_bytes(), format='jpeg') for p in pictures if Path(p).is_file()]
        return images + [out]
