"""3D tool pop-up: a stylised tool springs in, turns slowly, a label card appears, then it flies out.

params:
  tool       wrench | ratchet | screwdriver | hammer         (default wrench)
  label      text on the card, e.g. "3/8 in ratchet"          (default: tool name)
  sublabel   optional second line, e.g. "72-tooth"
  x, y       screen position of the tool centre (0..1)        (default 0.76, 0.32)
  size       tool length as a fraction of the SHORTER frame side (default 0.45; works for 9:16 and 16:9)
  in_s       pop-in time (s)                                  (default 0.5)
  out_s      fly-out time (s)                                 (default 0.45)
  spin_deg   gentle sway during the hold (degrees either way) (default 35)
  accent     brand colour name or #hex for grips/card stripe  (default orange)
"""

import math

import vfxlib as v


def _accent(name):
    return v.hex_color(name) if str(name).startswith("#") else v.brand(name)


def wrench(parent, accent):
    steel = v.material("steel", v.brand("chrome"), metallic=1.0, roughness=0.22)
    v.box("handle", (3.2, 0.42, 0.14), (0, 0, 0), steel, parent, bevel=0.05)
    head = v.cylinder("open_end", 0.62, 0.18, (1.95, 0, 0), (math.radians(90), 0, 0), steel, parent)
    slot = v.box("slot", (1.0, 0.5, 0.6), (2.35, 0, 0), None, parent, rotation=(0, 0, 0))
    slot.rotation_euler = (math.radians(90), 0, math.radians(20))
    v.boolean_cut(head, slot)
    v.torus("ring_end", 0.48, 0.16, (-1.9, 0, 0), (math.radians(90), 0, 0), steel, parent)
    v.box("grip_mark", (1.0, 0.44, 0.15), (-0.2, 0, 0), v.material("mark", accent, roughness=0.5), parent,
          bevel=0.03)
    return 4.4


def ratchet(parent, accent):
    steel = v.material("steel", v.brand("chrome"), metallic=1.0, roughness=0.2)
    grip = v.material("grip", accent, roughness=0.65)
    v.box("handle", (2.8, 0.34, 0.22), (-0.3, 0, 0), steel, parent, bevel=0.06)
    v.box("grip", (1.5, 0.42, 0.3), (-1.0, 0, 0), grip, parent, bevel=0.1)
    v.cylinder("head", 0.55, 0.38, (1.45, 0, 0), (math.radians(90), 0, 0), steel, parent)
    v.box("drive", (0.3, 0.3, 0.3), (1.45, 0.32, 0), steel, parent, bevel=0.02)
    v.box("lever", (0.4, 0.14, 0.12), (1.45, -0.24, 0.18), v.material("lever", v.brand("rubber"), roughness=0.5),
          parent, bevel=0.03)
    return 4.0


def screwdriver(parent, accent):
    steel = v.material("steel", v.brand("chrome"), metallic=1.0, roughness=0.18)
    grip = v.material("grip", accent, roughness=0.45)
    band = v.material("band", v.brand("brown"), roughness=0.5)
    rot = (0, math.radians(90), 0)
    v.cylinder("handle", 0.34, 1.6, (-1.2, 0, 0), rot, grip, parent, bevel=0.06)
    v.cylinder("band", 0.35, 0.18, (-0.6, 0, 0), rot, band, parent)
    v.cylinder("ferrule", 0.16, 0.25, (-0.28, 0, 0), rot, steel, parent)
    v.cylinder("shaft", 0.075, 2.2, (0.95, 0, 0), rot, steel, parent)
    v.box("tip", (0.25, 0.04, 0.17), (2.12, 0, 0), steel, parent)
    return 4.4


def hammer(parent, accent):
    wood = v.material("wood", v.hex_color("#8a5a32"), roughness=0.6)
    steel = v.material("steel", v.brand("chrome"), metallic=1.0, roughness=0.25)
    grip = v.material("grip", accent, roughness=0.7)
    rot = (0, math.radians(90), 0)
    v.cylinder("handle", 0.15, 3.4, (-0.2, 0, 0), rot, wood, parent)
    v.cylinder("grip", 0.19, 1.1, (-1.35, 0, 0), rot, grip, parent)
    v.box("head", (0.42, 0.42, 1.5), (1.55, 0, 0.15), steel, parent, bevel=0.05)
    v.cylinder("face", 0.26, 0.3, (1.55, 0, 0.95), (0, 0, 0), steel, parent)
    claw = v.box("claw", (0.3, 0.36, 0.9), (1.55, 0, -0.75), steel, parent, bevel=0.04)
    claw.rotation_euler = (0, math.radians(-25), 0)
    return 4.0


TOOLS = {"wrench": wrench, "ratchet": ratchet, "screwdriver": screwdriver, "hammer": hammer}


def build(ctx):
    p = ctx.params
    tool = p.get("tool", "wrench").lower()
    if tool not in TOOLS:
        raise ValueError(f"unknown tool '{tool}'; choose {sorted(TOOLS)} or use the free-form script effect")
    accent = _accent(p.get("accent", "orange"))
    x, y = float(p.get("x", 0.76)), float(p.get("y", 0.32))
    size = float(p.get("size", 0.45)) * min(ctx.world_w, ctx.world_h)
    t_in, t_out = float(p.get("in_s", 0.5)), float(p.get("out_s", 0.45))
    spin = math.radians(float(p.get("spin_deg", 35)))
    total = ctx.frames / ctx.fps
    v.add_studio_lights(ctx)

    anchor = v.empty("anchor", ctx.to_world(x, y))
    pivot = v.empty("pivot", (0, 0, 0), anchor)
    model = v.empty("model", (0, 0, 0), pivot)
    length = TOOLS[tool](model, accent)
    s = size / length
    model.scale = (s, s, s)
    model.rotation_euler = (math.radians(70), math.radians(-28), 0)   # tilt the tool toward camera

    # label card under the tool
    label = p.get("label") or tool.capitalize()
    card_h = size * (0.36 if p.get("sublabel") else 0.24)
    longest = max(len(label), len(p.get("sublabel") or ""))
    card_w = min(max(size * 0.8, card_h * 0.32 * longest + card_h * 0.6), ctx.world_w * 0.9)
    margin = ctx.world_w * 0.03
    card_pos = ctx.to_world(x, y) + v.Vector((0, -1.0, -size * 0.48))
    # keep the whole card inside the frame (vertical video is narrow)
    card_pos.x = max(-ctx.world_w / 2 + card_w / 2 + margin, min(ctx.world_w / 2 - card_w / 2 - margin, card_pos.x))
    card = v.empty("card", card_pos)
    fit = card_w * 0.88 / (0.55 * max(longest, 1))     # approx. glyph width 0.55 x font size
    v.box("card_bg", (card_w, 0.05, card_h), (0, 0, 0), v.material("card", v.brand("cream"), roughness=0.6),
          card, bevel=min(card_h, card_w) * 0.18)
    v.box("card_stripe", (card_w * 0.98, 0.06, card_h * 0.1), (0, -0.01, -card_h * 0.42),
          v.material("stripe", accent, roughness=0.5), card)
    ink = v.material("ink", v.brand("brown"), roughness=0.5)
    line_y = card_h * (0.12 if p.get("sublabel") else 0.0)
    v.text("label", label, size=min(card_h * (0.42 if p.get("sublabel") else 0.55), fit),
           location=(0, -0.06, line_y), mat=ink, parent=card, extrude=0.01)
    if p.get("sublabel"):
        v.text("sublabel", p["sublabel"], size=min(card_h * 0.26, fit), location=(0, -0.06, -card_h * 0.2),
               mat=ink, parent=card, extrude=0.005)

    def frame(f, t):
        hold_end = total - t_out
        if t < t_in:
            sc = v.ease_out_back(t / t_in, 2.2)
            rz = v.lerp(-1.2, 0, v.ease_out_cubic(t / t_in))
        elif t < hold_end:
            sc = 1.0
            rz = spin * math.sin(2 * math.pi * (t - t_in) / 3.0)   # sway, never end-on
        else:
            k = (t - hold_end) / t_out
            sc = 1.0 - v.ease_in_back(k, 1.8)
            rz = spin * math.sin(2 * math.pi * (hold_end - t_in) / 3.0) + 0.8 * v.ease_in_cubic(k)
        sc = max(sc, 0.0001)
        v.key(pivot, f, scale=(sc, sc, sc), rotation_euler=(0, 0, rz))
        bob = 0.06 * size * math.sin(t * 2.2)
        v.key(anchor, f, location=ctx.to_world(x, y) + v.Vector((0, 0, bob)))
        c_in = t_in + 0.15
        if t < c_in:
            cs = 0.0001
        elif t < c_in + 0.35:
            cs = max(v.ease_out_back((t - c_in) / 0.35, 1.6), 0.0001)
        elif t < hold_end - 0.1:
            cs = 1.0
        else:
            cs = max(1 - v.ease_in_cubic((t - hold_end + 0.1) / max(t_out, 1e-3)), 0.0001)
        # fully collapsed when hidden (a flattened card would still show as a thin line)
        v.key(card, f, scale=(0.0001,) * 3 if cs < 0.02 else ((1, 1, cs) if cs < 1 else (1, 1, 1)))

    ctx.each_frame(frame)
