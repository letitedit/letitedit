"""Helpers available to every effect template (runs inside Blender's Python).

Screen coordinates used by templates: x, y in [0, 1] with (0, 0) = top-left of the video frame.
World: camera looks along +Y; X is right, Z is up; the y=0 plane maps exactly onto the frame.
"""

import math
import random

import bpy
from mathutils import Vector

CAM_DISTANCE = 30.0
FOCAL_MM = 85.0
SENSOR_MM = 36.0

BRAND = {
    "cream": (0.937, 0.886, 0.769),
    "brown": (0.361, 0.227, 0.129),
    "orange": (0.780, 0.420, 0.180),
    "tan": (0.722, 0.541, 0.341),
    "window": (0.06, 0.07, 0.09),
    "chrome": (0.80, 0.80, 0.82),
    "rubber": (0.03, 0.03, 0.03),
}


def srgb_to_linear(c):
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)


def hex_color(value):
    value = value.lstrip("#")
    return srgb_to_linear(tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def brand(name):
    return srgb_to_linear(BRAND[name])


# ----------------------------------------------------------------------------- easing

def clamp01(t):
    return max(0.0, min(1.0, t))


def ease_out_cubic(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    t = clamp01(t)
    return t ** 3


def ease_in_out(t):
    t = clamp01(t)
    return 3 * t * t - 2 * t * t * t


def ease_out_back(t, s=1.70158):
    t = clamp01(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_back(t, s=1.70158):
    t = clamp01(t)
    return t * t * ((s + 1) * t - s)


def ease_out_expo(t):
    t = clamp01(t)
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def lerp(a, b, t):
    return a + (b - a) * t


# ----------------------------------------------------------------------------- context

class Ctx:
    def __init__(self, job):
        self.job = job
        self.params = job.get("params", {})
        self.width = job["width"]
        self.height = job["height"]
        self.fps = job["fps"]
        self.frames = job["frames"]
        self.world_w = CAM_DISTANCE * SENSOR_MM / FOCAL_MM
        self.world_h = self.world_w * self.height / self.width
        self.light = job.get("light") or {}
        self.rng = random.Random(job.get("seed", 7))
        self.scene = bpy.context.scene

    def to_world(self, x, y, depth=0.0):
        """Screen (x, y in 0..1, y down) -> world point on the frame plane (depth > 0 = farther)."""
        return Vector(((x - 0.5) * self.world_w, depth, (0.5 - y) * self.world_h))

    def units(self, frac_of_height):
        return frac_of_height * self.world_h

    def sec(self, s):
        return s * self.fps

    def each_frame(self, fn):
        """Call fn(frame, t_seconds) for every output frame (keyframe whatever it sets)."""
        for f in range(1, self.frames + 1):
            self.scene.frame_set(f)
            fn(f, (f - 1) / self.fps)


# ----------------------------------------------------------------------------- scene

def reset_scene(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Templates key every frame from Python easing functions; linear keys reproduce them exactly.
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    scene = bpy.context.scene
    scene.render.resolution_x = job["render_width"]
    scene.render.resolution_y = job["render_height"]
    scene.render.resolution_percentage = 100
    scene.render.fps = int(round(job["fps"]))
    scene.render.fps_base = scene.render.fps / job["fps"]
    scene.frame_start, scene.frame_end = 1, job["frames"]
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = job.get("view_transform", "Standard")
    scene.render.use_motion_blur = job.get("motion_blur", True)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = FOCAL_MM
    cam_data.sensor_width = SENSOR_MM
    cam_data.sensor_fit = "HORIZONTAL"
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (0, -CAM_DISTANCE, 0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    tint = (job.get("light") or {}).get("background_rgb") or [0.6, 0.6, 0.6]
    bg.inputs[0].default_value = (*srgb_to_linear([0.55 + 0.45 * c for c in tint]), 1)
    bg.inputs[1].default_value = 0.8
    return scene


def add_studio_lights(ctx, strength=1.0):
    side = ctx.light.get("brightest_side", {}).get("x", -0.3) or -0.3
    key_x = -8 if side < 0 else 8
    warm = ctx.light.get("warmth", 0.0) or 0.0
    key_color = (1.0, 1.0 - max(0, -warm) * 0.5, 1.0 - max(0, warm) * 0.6)
    lights = []
    for name, loc, energy, size, color in (
            ("Key", (key_x, -14, 9), 2200, 6, key_color),
            ("Fill", (-key_x, -16, 2), 700, 10, (0.92, 0.95, 1.0)),
            ("Rim", (0, 12, 8), 1500, 4, (1.0, 0.95, 0.9))):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy * strength
        data.size = size
        data.color = color
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        direction = Vector((0, 0, 0)) - Vector(loc)
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        ctx.scene.collection.objects.link(obj)
        lights.append(obj)
    return lights


# ----------------------------------------------------------------------------- building blocks

def material(name, color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, emission=None,
             emission_strength=0.0, alpha=1.0, blended=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    bsdf.inputs["Alpha"].default_value = alpha
    if blended or alpha < 1:
        mat.surface_render_method = "BLENDED"
    return mat


def bsdf(mat):
    return mat.node_tree.nodes["Principled BSDF"]


def link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def empty(name, location=(0, 0, 0), parent=None):
    obj = bpy.data.objects.new(name, None)
    obj.location = location
    return link(obj, parent)


def _finish(obj, mat, parent, bevel=0.0, smooth=False):
    if mat is not None:
        obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = "ANGLE"
    if smooth:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    if parent is not None:
        obj.parent = parent
    return obj


def box(name, size, location=(0, 0, 0), mat=None, parent=None, bevel=0.0, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return _finish(obj, mat, parent, bevel)


def cylinder(name, radius, depth, location=(0, 0, 0), rotation=(0, 0, 0), mat=None, parent=None,
             vertices=48, bevel=0.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                        location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    return _finish(obj, mat, parent, bevel, smooth=True)


def sphere(name, radius, location=(0, 0, 0), mat=None, parent=None, subdivisions=3):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdivisions, radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return _finish(obj, mat, parent, smooth=True)


def torus(name, major, minor, location=(0, 0, 0), rotation=(0, 0, 0), mat=None, parent=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, location=location,
                                     rotation=rotation, major_segments=48, minor_segments=16)
    obj = bpy.context.active_object
    obj.name = name
    return _finish(obj, mat, parent, smooth=True)


def text(name, body, size=1.0, location=(0, 0, 0), mat=None, parent=None, extrude=0.03,
         align="CENTER", rotation=(math.radians(90), 0, 0)):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.size = size
    curve.extrude = extrude
    curve.align_x = align
    curve.align_y = "CENTER"
    obj = bpy.data.objects.new(name, curve)
    obj.location = location
    obj.rotation_euler = rotation
    if mat is not None:
        curve.materials.append(mat)
    return link(obj, parent)


def boolean_cut(target, cutter):
    mod = target.modifiers.new("Cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    cutter.hide_render = True
    cutter.hide_viewport = True
    return mod


def key(obj, frame, **props):
    """Set and keyframe object properties: location, rotation_euler, scale (3-tuples)."""
    for prop, value in props.items():
        setattr(obj, prop, value)
        obj.keyframe_insert(data_path=prop, frame=frame)


def key_input(mat, input_name, frame, value):
    sock = bsdf(mat).inputs[input_name]
    sock.default_value = value
    sock.keyframe_insert("default_value", frame=frame)


def linear_keys():
    """Make every fcurve linear so per-frame keys reproduce the Python easing exactly."""
    for action in bpy.data.actions:
        for fc in getattr(action, "fcurves", []):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
