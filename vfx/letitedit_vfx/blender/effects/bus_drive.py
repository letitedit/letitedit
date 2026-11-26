"""3D bus: a boxy 1980s Wanderlodge built from code drives across the frame
(couch, table, dashboard...) with spinning wheels, a small bounce and a soft contact shadow.

params:
  start_x, end_x   screen x where the bus centre starts/ends (0..1; <0 or >1 = off screen)
                   (default -0.3 -> 1.3, left to right)
  ground_y         screen y of the surface the wheels sit on (0..1)            (default 0.78)
  length           bus length as a fraction of frame WIDTH                     (default 0.38)
  yaw_deg          turn toward the camera to show the front cap                (default 26)
  sign             text on the front sign                                      (default ROAD TRIP)
  bounce           suspension bounce amount (0..1)                             (default 0.5)
  ease             true = accelerate/brake, false = constant speed             (default true)
"""

import math

import vfxlib as v

L, H, W = 10.0, 2.55, 2.5          # body length / height / width in model units
WHEEL_R = 0.55


def build_bus(parent, sign_text):
    cream = v.material("cream", v.brand("cream"), roughness=0.45)
    brown = v.material("brown", v.brand("brown"), roughness=0.5)
    orange = v.material("orange", v.brand("orange"), roughness=0.5)
    tan = v.material("tan", v.brand("tan"), roughness=0.5)
    glass = v.material("glass", v.brand("window"), metallic=0.2, roughness=0.08)
    chrome = v.material("chrome", v.brand("chrome"), metallic=1.0, roughness=0.2)
    rubber = v.material("rubber", v.brand("rubber"), roughness=0.8)

    base_z = WHEEL_R * 0.95
    body = v.empty("body", (0, 0, 0), parent)
    v.box("shell", (L, W, H), (0, 0, base_z + H / 2), cream, body, bevel=0.22)
    v.box("roof_cap", (L * 0.97, W * 0.96, 0.18), (0, 0, base_z + H + 0.06), cream, body, bevel=0.08)
    # brand stripes along both sides (slightly proud of the body)
    for side in (-1, 1):
        y = side * (W / 2 + 0.012)
        for z, mat, hgt in ((0.95, brown, 0.22), (0.72, orange, 0.12), (0.56, tan, 0.1)):
            v.box(f"stripe_{side}_{z}", (L * 0.96, 0.03, hgt), (0, y, base_z + z), mat, body)
        v.box(f"windows_{side}", (L * 0.74, 0.03, 0.62), (-0.55, y, base_z + 1.62), glass, body, bevel=0.05)
        v.box(f"skirt_{side}", (L * 0.96, 0.03, 0.18), (0, y, base_z + 0.12), brown, body)
    # front cap: windshield, sign, headlights, bumper
    fx = L / 2 + 0.02
    v.box("windshield", (0.04, W * 0.86, 0.95), (fx, 0, base_z + 1.55), glass, body, bevel=0.04)
    v.box("sign_bg", (0.05, W * 0.8, 0.34), (fx + 0.01, 0, base_z + 2.3), brown, body, bevel=0.03)
    v.text("sign", sign_text, size=0.24, location=(fx + 0.05, 0, base_z + 2.3), mat=cream, parent=body,
           extrude=0.01, rotation=(math.radians(90), 0, math.radians(90)))
    for side in (-1, 1):
        v.cylinder(f"lamp_{side}", 0.13, 0.05, (fx + 0.02, side * 0.82, base_z + 0.62),
                   (0, math.radians(90), 0), v.material("lamp", (1, 1, 0.9), emission=(1, 0.95, 0.8),
                                                         emission_strength=3), body)
    v.box("bumper", (0.18, W * 1.02, 0.22), (fx + 0.05, 0, base_z + 0.22), chrome, body, bevel=0.05)
    v.box("grille", (0.04, W * 0.5, 0.35), (fx + 0.02, 0, base_z + 0.62), chrome, body)
    # roof air conditioners
    for x in (-2.5, 1.0):
        v.box(f"ac_{x}", (1.3, 1.1, 0.35), (x, 0, base_z + H + 0.3), cream, body, bevel=0.08)

    wheels = []
    for x in (L / 2 - 1.6, -L / 2 + 2.2, -L / 2 + 1.0):          # front axle + tandem rear
        for side in (-1, 1):
            hub = v.empty(f"wheel_{x}_{side}", (x, side * (W / 2 - 0.05), WHEEL_R), parent)
            v.cylinder("tire", WHEEL_R, 0.36, (0, 0, 0), (math.radians(90), 0, 0), rubber, hub)
            v.cylinder("rim", WHEEL_R * 0.55, 0.38, (0, 0, 0), (math.radians(90), 0, 0), chrome, hub)
            v.box("lug", (WHEEL_R * 0.9, 0.4, 0.08), (0, 0, 0), chrome, hub)   # makes rotation visible
            wheels.append(hub)
    return body, wheels


def shadow(parent):
    mat = v.bpy.data.materials.new("shadow")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    mix = nodes.new("ShaderNodeMixShader")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    dark = nodes.new("ShaderNodeEmission")
    dark.inputs[0].default_value = (0, 0, 0, 1)
    coord = nodes.new("ShaderNodeTexCoord")
    grad = nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "SPHERICAL"
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (2.0, 2.0, 2.0)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = 0.6
    ramp.color_ramp.elements[1].color = (0.6, 0.6, 0.6, 1)
    links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], grad.inputs["Vector"])
    links.new(grad.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(dark.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])
    mat.surface_render_method = "BLENDED"
    v.bpy.ops.mesh.primitive_plane_add(size=1)
    plane = v.bpy.context.active_object
    plane.name = "contact_shadow"
    plane.scale = (L * 0.62, W * 0.9, 1)
    plane.data.materials.append(mat)
    plane.parent = parent
    plane.location = (0, 0, 0.02)
    return plane


def build(ctx):
    p = ctx.params
    x0, x1 = float(p.get("start_x", -0.3)), float(p.get("end_x", 1.3))
    gy = float(p.get("ground_y", 0.78))
    length_world = float(p.get("length", 0.38)) * ctx.world_w
    yaw = math.radians(float(p.get("yaw_deg", 26)))
    bounce = float(p.get("bounce", 0.5))
    direction = 1 if x1 >= x0 else -1
    v.add_studio_lights(ctx, strength=1.1)

    rig = v.empty("rig", ctx.to_world(x0, gy))
    scale = length_world / L
    model = v.empty("model", (0, 0, 0), rig)
    model.scale = (scale, scale, scale)
    # face the travel direction, turned a little toward the camera (camera looks along +Y)
    model.rotation_euler = (math.radians(6), 0, (0 if direction > 0 else math.pi) - direction * yaw)
    body, wheels = build_bus(model, p.get("sign", "ROAD TRIP"))
    sh = shadow(model)
    sh.rotation_euler = (math.radians(-70), 0, 0)   # camera is level: tilt the shadow so it reads

    total = ctx.frames / ctx.fps
    start, end = ctx.to_world(x0, gy), ctx.to_world(x1, gy)
    travel = (end - start).length
    ease = p.get("ease", True)

    def frame(f, t):
        k = t / max(total - 1 / ctx.fps, 1e-3)
        pos_k = v.ease_in_out(k) if ease else k
        pos = start.lerp(end, pos_k)
        v.key(rig, f, location=pos)
        dist = travel * pos_k / scale
        for hub in wheels:
            v.key(hub, f, rotation_euler=(0, dist / WHEEL_R, 0))
        bz = bounce * 0.06 * (math.sin(t * 13.0) + 0.5 * math.sin(t * 7.3))
        pitch = bounce * 0.012 * math.sin(t * 9.0)
        v.key(body, f, location=(0, 0, bz), rotation_euler=(0, pitch, 0))

    ctx.each_frame(frame)
