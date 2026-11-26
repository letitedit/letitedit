"""Stylised explosion: flash, billowing fireball, dark smoke, flying sparks.

Composite it with mode="composite" + occlusion="subject" to put it BEHIND the person in the shot;
the compositor then adds glow, a light flicker on the plate and a short camera shake.

params:
  x, y         blast centre on screen (0..1)                 (default 0.5, 0.55)
  size         fireball diameter as a fraction of frame height (default 0.7)
  delay_s      seconds before the blast starts                (default 0.15)
  smoke        include rolling smoke                          (default true)
  sparks       number of sparks                               (default 60)
  palette      "fire" (default) | "blue" | "green"            (stylised colours)
"""

import math

import vfxlib as v

PALETTES = {
    "fire": [(1.0, 0.82, 0.35), (1.0, 0.42, 0.06), (0.7, 0.1, 0.02), (0.15, 0.03, 0.015)],
    "blue": [(0.85, 0.95, 1.0), (0.35, 0.65, 1.0), (0.1, 0.25, 0.9), (0.03, 0.04, 0.25)],
    "green": [(0.9, 1.0, 0.8), (0.45, 1.0, 0.3), (0.1, 0.6, 0.08), (0.02, 0.2, 0.02)],
}


def ramp(colors, t):
    t = v.clamp01(t) * (len(colors) - 1)
    i = min(int(t), len(colors) - 2)
    k = t - i
    return tuple(v.lerp(a, b, k) for a, b in zip(colors[i], colors[i + 1]))


def fire_material(name, seed):
    """Emission modulated by 3D noise so fire billows instead of reading as a flat blob.
    Returns (material, hot colour socket, cool colour socket, strength socket, alpha socket)."""
    mat = v.material(name, (0, 0, 0), emission=(1, 1, 1), emission_strength=1, alpha=0, blended=True)
    nt = mat.node_tree
    bs = v.bsdf(mat)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.2
    noise.inputs["Detail"].default_value = 6.0
    noise.noise_dimensions = "4D"            # must be set before the W input exists
    noise.inputs["W"].default_value = seed * 1.7
    rng = nt.nodes.new("ShaderNodeMapRange")
    rng.inputs["From Min"].default_value = 0.32
    rng.inputs["From Max"].default_value = 0.72
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mult = nt.nodes.new("ShaderNodeMath")
    mult.operation = "MULTIPLY"
    boost = nt.nodes.new("ShaderNodeMath")
    boost.operation = "MULTIPLY_ADD"
    boost.inputs[1].default_value = 1.1
    boost.inputs[2].default_value = 0.25
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], rng.inputs["Value"])
    nt.links.new(rng.outputs["Result"], mix.inputs["Factor"])
    nt.links.new(mix.outputs["Result"], bs.inputs["Emission Color"])
    nt.links.new(rng.outputs["Result"], boost.inputs[0])
    nt.links.new(boost.outputs[0], mult.inputs[0])
    nt.links.new(mult.outputs[0], bs.inputs["Emission Strength"])
    return mat, mix.inputs[7], mix.inputs[6], mult.inputs[1], bs.inputs["Alpha"], noise.inputs["W"]


def key_socket(sock, frame, value):
    sock.default_value = value
    sock.keyframe_insert("default_value", frame=frame)


def noisy(name, radius, location, mat, scale, seed):
    obj = v.sphere(name, radius, location, mat, subdivisions=4)
    tex = v.bpy.data.textures.new(name + "_tex", "CLOUDS")
    tex.noise_scale = 0.55
    tex.noise_depth = 2
    mod = obj.modifiers.new("Billow", "DISPLACE")
    mod.texture = tex
    mod.strength = radius * scale
    mod.texture_coords = "OBJECT"
    coords = v.empty(name + "_coords", location)
    coords.location.x += seed * 3.1
    mod.texture_coords_object = coords
    return obj, coords


def build(ctx):
    p = ctx.params
    cx, cy = float(p.get("x", 0.5)), float(p.get("y", 0.55))
    size = ctx.units(float(p.get("size", 0.7)))
    delay = float(p.get("delay_s", 0.15))
    colors = PALETTES.get(p.get("palette", "fire"), PALETTES["fire"])
    centre = ctx.to_world(cx, cy, depth=2.0)
    rng = ctx.rng
    ctx.scene.view_settings.view_transform = "Standard"
    v.add_studio_lights(ctx, strength=0.4)

    flash_mat = v.material("flash", (1, 1, 1), emission=(1, 0.95, 0.85), emission_strength=0, alpha=0,
                           blended=True)
    flash = v.sphere("flash", size * 0.5, centre, flash_mat)

    balls = []
    for i in range(7):
        mat, hot, cool, strength_sock, alpha_sock, w_sock = fire_material(f"fire{i}", i)
        off = v.Vector((rng.uniform(-1, 1), rng.uniform(-0.4, 0.4), rng.uniform(-0.6, 1))) * size * 0.18
        obj, coords = noisy(f"fire{i}", size * rng.uniform(0.22, 0.32), centre + off, mat, 0.6, i)
        balls.append((obj, coords, (hot, cool, strength_sock, alpha_sock, w_sock), off,
                      rng.uniform(0.85, 1.15), rng.uniform(0, 0.12)))

    smokes = []
    if p.get("smoke", True):
        for i in range(8):
            shade = rng.uniform(0.05, 0.14)
            mat = v.material(f"smoke{i}", (shade, shade, shade * 0.95), roughness=1.0, alpha=0, blended=True)
            off = v.Vector((rng.uniform(-1, 1), rng.uniform(0.2, 0.8), rng.uniform(-0.2, 1.2))) * size * 0.25
            obj, coords = noisy(f"smoke{i}", size * rng.uniform(0.25, 0.4), centre + off, mat, 0.9, 10 + i)
            smokes.append((obj, coords, mat, off, rng.uniform(0.25, 0.45)))

    sparks = []
    spark_mat = v.material("spark", (0, 0, 0), emission=colors[1], emission_strength=8, alpha=1, blended=True)
    for i in range(int(p.get("sparks", 60))):
        obj = v.sphere(f"spark{i}", size * 0.012, centre, spark_mat, subdivisions=1)
        ang = rng.uniform(math.radians(-20), math.radians(200))
        speed = rng.uniform(0.9, 2.2) * size
        vel = v.Vector((math.cos(ang) * speed, rng.uniform(-0.3, 0.3) * speed, math.sin(ang) * speed * 1.1))
        sparks.append((obj, vel, rng.uniform(0.5, 1.0)))

    def frame(f, t):
        te = t - delay
        # flash: a few frames of white-hot light
        fl = v.clamp01(1 - te / 0.12) if te >= 0 else 0.0
        v.key_input(flash_mat, "Emission Strength", f, 8 * fl)
        v.key_input(flash_mat, "Alpha", f, 0.9 * fl)
        flash.scale = (0.4 + te * 4,) * 3 if te > 0 else (0.0001,) * 3
        flash.keyframe_insert("scale", frame=f)

        for obj, coords, (hot, cool, strength_sock, alpha_sock, w_sock), off, gain, lag in balls:
            tt = te - lag
            if tt <= 0:
                sc, strength, alpha, heat = 0.0001, 0.0, 0.0, 0.0
            else:
                sc = 0.15 + 1.0 * v.ease_out_expo(tt / 0.7) * gain + 0.15 * tt
                heat = v.clamp01(tt / 1.3)
                strength = 3.2 * (1 - heat) ** 1.4 + 0.7
                alpha = 1.0 - v.ease_in_cubic(v.clamp01((tt - 0.9) / 0.6))
            col = ramp(colors, heat)
            dark = ramp(colors, min(1.0, heat + 0.45))
            v.key(obj, f, scale=(sc, sc, sc),
                  location=centre + off * (1 + 1.5 * max(tt, 0)) + v.Vector((0, 0, 0.12 * size * max(tt, 0) ** 1.3)))
            v.key(coords, f, location=coords.location + v.Vector((0, 0, -0.05)))
            key_socket(hot, f, (*col, 1))
            key_socket(cool, f, (*dark, 1))
            key_socket(strength_sock, f, strength)
            key_socket(alpha_sock, f, alpha)
            key_socket(w_sock, f, w_sock.default_value + 0.06)

        for obj, coords, mat, off, start in smokes:
            tt = te - start
            if tt <= 0:
                sc, alpha = 0.0001, 0.0
            else:
                sc = 0.3 + 1.1 * v.ease_out_cubic(tt / 1.6)
                alpha = 0.9 * v.ease_out_cubic(tt / 0.4) * (1 - v.ease_in_cubic(v.clamp01((tt - 1.2) / 1.2)))
            v.key(obj, f, scale=(sc, sc, sc),
                  location=centre + off + v.Vector((0, 0, 0.35 * size * max(tt, 0))))
            v.key(coords, f, location=coords.location + v.Vector((0, 0, -0.04)))
            v.key_input(mat, "Alpha", f, alpha)

        for obj, vel, life in sparks:
            tt = te
            if tt <= 0 or tt > life:
                v.key(obj, f, scale=(0.0001,) * 3)
                continue
            pos = centre + vel * tt + v.Vector((0, 0, -4.5 * size * tt * tt))
            vz = vel.z - 9.0 * size * tt
            stretch = 1 + 6 * math.hypot(vel.x, vz) / (size * 3)
            fade = 1 - tt / life
            v.key(obj, f, location=pos, scale=(stretch * fade, fade, fade),
                  rotation_euler=(0, -math.atan2(vz, vel.x), 0))

    ctx.each_frame(frame)
