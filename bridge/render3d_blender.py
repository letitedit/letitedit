"""Runs INSIDE Blender (blender -b --factory-startup -P render3d_blender.py -- <job.json>). Driven by render3d.py.

job.json: {mode: 'list'|'render', model, original_dir, out_dir, ...render settings (see render3d.py)}
list   -> <out_dir>/list.json   objects, materials, bounds, cameras, lights of the model
render -> <out_dir>/f_00000.png ... (RGBA) and <out_dir>/frames.json (per frame: camera, callout anchors in pixels)
Nothing is ever saved back to the model file.
"""
import fnmatch
import json
import math
import os
import sys
import traceback

import bpy
from mathutils import Matrix, Vector

ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
MESHLIKE = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME', 'GREASEPENCIL'}


def log(*a):
    print('[render3d]', *a, flush=True)


# ------------------------------------------------------------------ loading

def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def rebase_paths(original_dir):
    """Relative image/library paths of a copied .blend point at the original folder (read only)."""
    if not original_dir:
        return
    for coll in (bpy.data.images, bpy.data.libraries):
        for it in coll:
            fp = getattr(it, 'filepath', '')
            if fp.startswith('//') and not getattr(it, 'packed_file', None):
                it.filepath = os.path.normpath(os.path.join(original_dir, fp[2:]))


def load(job):
    path = job['model']
    if path in ('builtin:title', 'builtin:logo'):
        build_builtin(job)
        return
    ext = os.path.splitext(path)[1].lower()
    if ext == '.blend':
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
        rebase_paths(job.get('original_dir'))
        if job.get('scene') and job['scene'] in bpy.data.scenes:
            bpy.context.window.scene = bpy.data.scenes[job['scene']]
        return
    clear_scene()
    if ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == '.obj':
        try:
            bpy.ops.wm.obj_import(filepath=path)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in ('.stl',):
        bpy.ops.wm.stl_import(filepath=path)
    elif ext in ('.ply',):
        bpy.ops.wm.ply_import(filepath=path)
    elif ext in ('.usd', '.usda', '.usdc', '.usdz'):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext in ('.dae',):
        bpy.ops.wm.collada_import(filepath=path)
    else:
        raise ValueError(f'unsupported model type {ext}')


def _builtin_material(name, color, metallic=0.0, roughness=0.35):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*hex_rgb(color), 1.0)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*hex_rgb(color), 1.0)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    return m


def _builtin_text(label, job, depth=0.11, front=True):
    cu = bpy.data.curves.new('Extruded lettering', type='FONT')
    cu.body = label
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.size = 1.0
    cu.extrude = depth
    cu.bevel_depth = 0.018
    cu.bevel_resolution = 3
    if job.get('font_path'):
        cu.font = bpy.data.fonts.load(job['font_path'])
    ob = bpy.data.objects.new('3D title', cu)
    bpy.context.collection.objects.link(ob)
    ob.rotation_euler[0] = math.pi / 2
    cu.materials.append(_builtin_material('Metallic sides', job.get('side_color', '#FF7468'), .42, .24))
    if front:
        face = cu.copy()
        face.name = 'Bright lettering face'
        face.extrude = .003
        face.bevel_depth = .005
        face.materials.clear()
        face.materials.append(_builtin_material('Lit face', job.get('front_color', '#F8F5ED'), .16, .24))
        front_obj = bpy.data.objects.new('3D title face', face)
        bpy.context.collection.objects.link(front_obj)
        front_obj.rotation_euler[0] = math.pi / 2
        front_obj.location.y = -(depth + .021)
    return ob


def build_builtin(job):
    """Our own Blender geometry; no stock model or external effect is required."""
    clear_scene()
    if job['model'] == 'builtin:title':
        _builtin_text(job.get('text', 'YOUR TITLE'), job)
        return
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    base = bpy.context.object
    base.name = 'Logo body'
    base.dimensions = (2.0, .34, 2.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = base.modifiers.new('Soft metal edges', 'BEVEL')
    bevel.width = .16
    bevel.segments = 5
    base.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    base.data.materials.append(_builtin_material('Logo shell', job.get('side_color', '#FF7468'), .48, .25))
    glyph = _builtin_text(job.get('text', 'L'), job, depth=.045)
    glyph.location.y = -.27
    glyph.scale = (1.55, 1.55, 1.55)
    face = bpy.data.objects.get('3D title face')
    if face:
        face.location.y = -.27 - (.045 + .021) * 1.55
        face.scale = glyph.scale


def renderable(o):
    if o.type not in MESHLIKE:
        return False
    if o.hide_render:
        return False
    try:
        if not o.visible_get():
            # hidden in viewport but may still render; count objects that render
            pass
    except Exception:
        pass
    # excluded collections
    for c in o.users_collection:
        if c.hide_render:
            return False
    return True


def world_bbox(objs, depsgraph):
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    n = 0
    for o in objs:
        oe = o.evaluated_get(depsgraph)
        pts = None
        if o.type in ('CURVE', 'FONT', 'SURFACE'):      # their bound_box can be loose: measure the evaluated mesh
            try:
                me = oe.to_mesh()
                if me is not None and len(me.vertices):
                    import numpy as np
                    co = np.empty(len(me.vertices) * 3, dtype='float32')
                    me.vertices.foreach_get('co', co)
                    co = co.reshape(-1, 3)
                    a, b = co.min(0), co.max(0)
                    pts = [Vector((x, y, z)) for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]
                oe.to_mesh_clear()
            except Exception:
                pts = None
        for c in (pts if pts is not None else oe.bound_box):
            w = oe.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
            n += 1
    if not n:
        return None
    return lo, hi


def obj_materials(o):
    return [s.material.name for s in o.material_slots if s.material]


def ground_like(objs, dg, ignore=None):
    """Objects left out of the subject's bounds: names in `ignore`, or (ignore None) flat objects (thinnest side under
    0.1% of the largest) whose largest side is over twice the size of everything else together."""
    if ignore is not None:
        out = []
        for spec in ignore:
            out += match_objects(spec, objs)
        return out
    out = []
    for o in objs:
        bb = world_bbox([o], dg)
        if not bb:
            continue
        size = bb[1] - bb[0]
        big, small = max(size), min(size)
        if big <= 0 or small > big * 0.001:
            continue
        rest = world_bbox([x for x in objs if x is not o], dg)
        if rest and big > 2 * max(rest[1] - rest[0]):
            out.append(o)
    return out


def list_model(job):
    dg = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene
    objs = []
    for o in scene.objects:
        rec = {'name': o.name, 'type': o.type, 'parent': o.parent.name if o.parent else None,
               'collections': [c.name for c in o.users_collection], 'renders': renderable(o),
               'materials': obj_materials(o)}
        if o.type in MESHLIKE:
            bb = world_bbox([o], dg)
            if bb:
                rec['bounds'] = [list(map(lambda v: round(v, 4), bb[0])), list(map(lambda v: round(v, 4), bb[1]))]
            if o.type == 'MESH':
                rec['vertices'] = len(o.data.vertices)
                rec['faces'] = len(o.data.polygons)
        objs.append(rec)
    vis = [o for o in scene.objects if renderable(o)]
    gl = ground_like(vis, dg)
    bb = world_bbox(vis, dg)
    sb = world_bbox([o for o in vis if o not in gl], dg)
    mats = {}
    for o in vis:
        for m in obj_materials(o):
            mats.setdefault(m, []).append(o.name)
    out = {'objects': objs, 'materials': [{'name': k, 'objects': v} for k, v in sorted(mats.items())],
           'bounds': [list(bb[0]), list(bb[1])] if bb else None,
           'size': list(bb[1] - bb[0]) if bb else None,
           'ground_like': [o.name for o in gl],
           'subject_bounds': [list(sb[0]), list(sb[1])] if sb else None,
           'subject_size': list(sb[1] - sb[0]) if sb else None,
           'unit_scale': scene.unit_settings.scale_length, 'unit_system': scene.unit_settings.system,
           'length_unit': scene.unit_settings.length_unit,
           'cameras': [o.name for o in scene.objects if o.type == 'CAMERA'],
           'lights': [o.name for o in scene.objects if o.type == 'LIGHT'],
           'scene': scene.name, 'scenes': [s.name for s in bpy.data.scenes],
           'blender': bpy.app.version_string}
    return out


# ------------------------------------------------------------------ targets

def match_objects(spec, objs):
    """'name' exact, else case-insensitive glob/substring on object names, collection names ('collection:X')."""
    s = str(spec)
    if s.lower().startswith('collection:'):
        want = s.split(':', 1)[1].lower()
        return [o for o in objs if any(fnmatch.fnmatch(c.name.lower(), want) or want in c.name.lower()
                                       for c in o.users_collection)]
    if s.lower().startswith('material:'):
        return []
    exact = [o for o in objs if o.name == s]
    if exact:
        return exact
    low = s.lower()
    if any(ch in low for ch in '*?['):
        return [o for o in objs if fnmatch.fnmatch(o.name.lower(), low)]
    return [o for o in objs if low in o.name.lower()]


def match_materials(spec):
    s = str(spec)
    if not s.lower().startswith('material:'):
        return []
    want = s.split(':', 1)[1]
    exact = [m for m in bpy.data.materials if m.name == want]
    if exact:
        return exact
    low = want.lower()
    if any(ch in low for ch in '*?['):
        return [m for m in bpy.data.materials if fnmatch.fnmatch(m.name.lower(), low)]
    return [m for m in bpy.data.materials if low in m.name.lower()]


def target_points(spec, objs, dg):
    """World-space points (bbox corners or material face vertices) of a target."""
    mats = match_materials(spec)
    pts = []
    if mats:
        names = {m.name for m in mats}
        for o in objs:
            if o.type != 'MESH':
                continue
            idx = {i for i, sl in enumerate(o.material_slots) if sl.material and sl.material.name in names}
            if not idx:
                continue
            oe = o.evaluated_get(dg)
            me = oe.to_mesh()
            mw = oe.matrix_world
            vs = set()
            for p in me.polygons:
                if p.material_index in idx:
                    vs.update(p.vertices)
            step = max(1, len(vs) // 4000)
            for k, v in enumerate(sorted(vs)):
                if k % step == 0:
                    pts.append(mw @ me.vertices[v].co)
            oe.to_mesh_clear()
        return pts
    for o in match_objects(spec, objs):
        oe = o.evaluated_get(dg)
        pts += [oe.matrix_world @ Vector(c) for c in oe.bound_box]
    return pts


def bbox_of(pts):
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


# ------------------------------------------------------------------ materials

def hex_rgb(h, default=(1, 0.7, 0)):
    if isinstance(h, (list, tuple)):
        v = [float(x) for x in h][:3]
        return tuple(x / 255.0 if max(v) > 1 else x for x in v)
    h = str(h or '').lstrip('#')
    if len(h) not in (6, 8):
        return default
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)   # to linear


def node(nt, typ):
    return nt.nodes.new(typ)


def set_blend(mat):
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass
    for attr, val in (('show_transparent_back', True), ('use_transparency_overlap', True)):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass


def ghost_material(name, color, alpha, edge, strength):
    """X-ray body: transparent with an emissive fresnel edge."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = node(nt, 'ShaderNodeOutputMaterial')
    lw = node(nt, 'ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.35
    mp = node(nt, 'ShaderNodeMath')
    mp.operation = 'MULTIPLY_ADD'
    lw_out = lw.outputs['Facing']
    nt.links.new(lw_out, mp.inputs[0])
    mp.inputs[1].default_value = max(0.0, float(edge))
    mp.inputs[2].default_value = max(0.0, float(alpha))
    clamp = node(nt, 'ShaderNodeClamp')
    nt.links.new(mp.outputs[0], clamp.inputs['Value'])
    tr = node(nt, 'ShaderNodeBsdfTransparent')
    em = node(nt, 'ShaderNodeEmission')
    em.inputs['Color'].default_value = (*color, 1)
    em.inputs['Strength'].default_value = float(strength)
    mix = node(nt, 'ShaderNodeMixShader')
    nt.links.new(clamp.outputs[0], mix.inputs['Fac'])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    set_blend(m)
    try:
        m.use_transparent_shadow = True
    except Exception:
        pass
    return m


def solid_material(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value = (*color, 1)
    for key in ('Emission Color', 'Emission'):
        if key in p.inputs:
            p.inputs[key].default_value = (*color, 1)
            break
    if 'Emission Strength' in p.inputs:
        p.inputs['Emission Strength'].default_value = float(strength)
    p.inputs['Roughness'].default_value = 0.45
    return m


def glow_copy(mat, color, strength):
    m = mat.copy()
    m.name = mat.name + ' (highlight)'
    if m.use_nodes and m.node_tree:
        for p in [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']:
            for key in ('Emission Color', 'Emission'):
                if key in p.inputs:
                    for l in list(p.inputs[key].links):
                        m.node_tree.links.remove(l)
                    p.inputs[key].default_value = (*color, 1)
                    break
            if 'Emission Strength' in p.inputs:
                for l in list(p.inputs['Emission Strength'].links):
                    m.node_tree.links.remove(l)
                p.inputs['Emission Strength'].default_value = float(strength)
    return m


def assign_all(o, mat):
    if o.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT'):
        return
    if not o.material_slots:
        o.data.materials.append(mat)
    for s in o.material_slots:
        s.link = 'OBJECT' if s.link == 'OBJECT' else s.link
        s.material = mat


def replace_material(o, names, make):
    for s in o.material_slots:
        if s.material and s.material.name in names:
            s.material = make(s.material)


# ------------------------------------------------------------------ lights / world

def set_world(color, strength):
    w = bpy.data.worlds.new('render3d world')
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == 'BACKGROUND')
    bg.inputs['Color'].default_value = (*color, 1)
    bg.inputs['Strength'].default_value = strength
    bpy.context.scene.world = w
    return w


def add_light(name, kind, loc, target, energy, size, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == 'AREA':
        ld.size = size
    elif kind == 'SUN':
        ld.angle = math.radians(size)
    o = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return o


def lighting(preset, center, radius, opts):
    scene = bpy.context.scene
    if preset == 'model':
        return
    for o in scene.objects:
        if o.type == 'LIGHT':
            o.hide_render = True
    r = max(radius, 1e-3)
    c = Vector(center)
    k = float(opts.get('light_strength', 1.0))
    if preset == 'studio':
        set_world(hex_rgb(opts.get('world_color', '#8a8f99')), 0.6 * k)
        e = 900 * r * r * k
        add_light('key', 'AREA', c + Vector((-2.2 * r, -2.6 * r, 2.4 * r)), c, e, 2.0 * r)
        add_light('fill', 'AREA', c + Vector((2.8 * r, -1.6 * r, 1.0 * r)), c, e * 0.35, 3.0 * r)
        add_light('rim', 'AREA', c + Vector((0.5 * r, 3.0 * r, 2.2 * r)), c, e * 0.8, 1.5 * r)
    elif preset in ('daylight', 'sunset', 'night'):
        if preset == 'daylight':
            set_world(hex_rgb(opts.get('world_color', '#9dbbe0')), 0.9 * k)
            add_light('sun', 'SUN', c + Vector((-1, -1.2, 1.6)), c, 4.0 * k, 2.0, hex_rgb('#fff4e5'))
        elif preset == 'sunset':
            set_world(hex_rgb(opts.get('world_color', '#5a6a8c')), 0.5 * k)
            add_light('sun', 'SUN', c + Vector((-1.5, -0.6, 0.25)), c, 3.5 * k, 3.0, hex_rgb('#ff9a4a'))
        else:
            set_world(hex_rgb(opts.get('world_color', '#0b1220')), 0.35 * k)
            add_light('moon', 'SUN', c + Vector((1, -0.5, 1.2)), c, 0.35 * k, 1.0, hex_rgb('#9bb6ff'))
            add_light('warm', 'AREA', c + Vector((-1.6 * r, -1.8 * r, 0.6 * r)), c, 250 * r * r * k, 0.8 * r,
                      hex_rgb('#ffb066'))
    elif preset == 'flat':
        set_world(hex_rgb(opts.get('world_color', '#ffffff')), 1.0 * k)
    else:
        raise ValueError(f'unknown lighting {preset}')


# ------------------------------------------------------------------ camera path

def ease(t, kind):
    t = max(0.0, min(1.0, t))
    if kind in (None, 'linear'):
        return t
    if kind in ('ease_in_out', 'smooth', 'in_out'):
        return t * t * (3 - 2 * t)
    if kind in ('ease_in', 'in'):
        return t * t
    if kind in ('ease_out', 'out'):
        return 1 - (1 - t) * (1 - t)
    if kind == 'sine':
        return 0.5 - 0.5 * math.cos(math.pi * t)
    if kind in ('cubic', 'ease_in_out_cubic'):
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    if kind in ('expo', 'ease_out_expo'):
        return 1 if t >= 1 else 1 - 2 ** (-10 * t)
    return t


def lerp(a, b, t):
    return a + (b - a) * t


def pose_at(keys, t, easing):
    """keys: [{t, az, el, dist, focus, lens, roll}] sorted by t."""
    if t <= keys[0]['t']:
        return keys[0]
    if t >= keys[-1]['t']:
        return keys[-1]
    for a, b in zip(keys, keys[1:]):
        if a['t'] <= t <= b['t']:
            u = (t - a['t']) / max(1e-9, b['t'] - a['t'])
            u = ease(u, b.get('easing', easing))
            out = {}
            for k in ('az', 'el', 'lens', 'roll'):
                out[k] = lerp(a[k], b[k], u)
            out['dist'] = math.exp(lerp(math.log(a['dist']), math.log(b['dist']), u))
            out['focus'] = [lerp(x, y, u) for x, y in zip(a['focus'], b['focus'])]
            if a.get('pos') is not None and b.get('pos') is not None:
                out['pos'] = [lerp(x, y, u) for x, y in zip(a['pos'], b['pos'])]
            return out
    return keys[-1]


def cam_location(p):
    if p.get('pos') is not None:
        return Vector(p['pos'])
    az, el = math.radians(p['az']), math.radians(p['el'])
    f = Vector(p['focus'])
    # az 0: camera on -Y looking toward +Y (Blender's front view); az 90: camera on +X (right view)
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    return f + d * p['dist']



def subject(spec, objs, dg, center, radius, info, bounds=None):
    """(center, radius, lo, hi) of 'model', a target, or [x, y, z] (a box of the model's radius around it)."""
    if spec in (None, 'model'):
        lo, hi = bounds
        return Vector(center), radius, Vector(lo), Vector(hi)
    if isinstance(spec, (list, tuple)) and len(spec) == 3:
        c = Vector(spec)
        e = Vector((radius, radius, radius)) / math.sqrt(3)
        return c, radius, c - e, c + e
    pts = target_points(spec, objs, dg)
    if not pts:
        info['missing'].append(spec)
        lo, hi = bounds
        return Vector(center), radius, Vector(lo), Vector(hi)
    a, b = bbox_of(pts)
    return (a + b) / 2, max((b - a).length / 2, radius * 0.02), a, b


def half_angles(lens, aspect):
    """Half field of view (horizontal, vertical) in radians; 36 mm sensor across the longer side."""
    if aspect >= 1:
        th = 18.0 / lens
        return math.atan(th), math.atan(th / aspect)
    tv = 18.0 / lens
    return math.atan(tv * aspect), math.atan(tv)


def fit_distance(r, framing, lens, aspect):
    hh, hv = half_angles(lens, aspect)
    return r / math.sin(min(hh, hv)) / max(1e-3, float(framing))


def fit_box(c, lo, hi, az, el, framing, lens, aspect):
    """Distance at which the box's corners fill `framing` of the frame (width or height, whichever binds)."""
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))     # focus -> camera
    fwd = -d
    right = fwd.cross(Vector((0, 0, 1)))
    if right.length < 1e-6:
        right = Vector((1, 0, 0))
    right.normalize()
    up = right.cross(fwd).normalized()
    hh, hv = half_angles(lens, aspect)
    th, tv = math.tan(hh) * framing, math.tan(hv) * framing
    best = 0.0
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                r = Vector((x, y, z)) - c
                need = max(abs(r.dot(right)) / th, abs(r.dot(up)) / tv) + r.dot(d)
                best = max(best, need)
    return max(best, (hi - lo).length * 0.05)


def compile_move(move, job, center, radius, objs, dg, aspect, info):
    """Camera keys [{t, az, el, dist, focus, lens, roll, pos?}] for a move (all angles in degrees)."""
    typ = move.get('type', 'orbit')
    dur = float(job['duration'])
    lens0 = float(move.get('lens', 35.0))
    az = float(move.get('azimuth', 30.0))
    el = float(move.get('elevation', 12.0))
    framing = float(move.get('framing', 0.9))
    roll = float(move.get('roll', 0.0))
    fit = move.get('fit', 'box')
    bounds = info['bounds']

    def dist_for(focus_spec, az_, el_, framing_, lens_):
        c, r, lo, hi = subject(focus_spec, objs, dg, center, radius, info, bounds)
        if fit == 'sphere':
            return c, fit_distance(r, framing_, lens_, aspect)
        return c, fit_box(c, lo, hi, az_, el_, framing_, lens_, aspect)

    def key(t, az_, el_, focus_spec, framing_, lens_=lens0, dist=None, easing=None):
        c, d = dist_for(focus_spec, az_, el_, framing_, lens_)
        if dist is not None:
            d = float(dist) * radius
        k = {'t': t, 'az': az_, 'el': el_, 'dist': d, 'focus': list(c), 'lens': lens_, 'roll': roll}
        if easing:
            k['easing'] = easing
        return k

    focus = move.get('focus', 'model')
    if typ == 'keys':
        out = []
        for k in move['keys']:
            out.append(key(float(k['t']), float(k.get('azimuth', az)), float(k.get('elevation', el)),
                           k.get('focus', focus), float(k.get('framing', framing)), float(k.get('lens', lens0)),
                           k.get('distance'), k.get('easing')))
            out[-1]['roll'] = float(k.get('roll', roll))
        return sorted(out, key=lambda k: k['t'])
    if typ == 'turntable':
        dist = move.get('distance')
        if dist is None:
            t0, t1 = float(move.get('turn_from', 0.0)), float(move.get('turn_to', 360.0))
            n = 36
            dist = max(dist_for(focus, az - (t0 + (t1 - t0) * i / n), el, framing, lens0)[1] for i in range(n + 1)) / radius
        k = key(0.0, az, el, focus, framing, dist=dist)
        return [k, dict(k, t=dur)]
    if typ in ('static', 'still'):
        k = key(0.0, az, el, focus, framing, dist=move.get('distance'))
        return [k, dict(k, t=dur)]
    if typ == 'orbit':
        a0 = float(move.get('azimuth_from', az))
        a1 = float(move.get('azimuth_to', a0 + float(move.get('degrees', 120.0))))
        e0 = float(move.get('elevation_from', el))
        e1 = float(move.get('elevation_to', el))
        dist = move.get('distance')
        if dist is None:      # one distance for the whole orbit: the largest fit along the path
            n = 24
            best = max(dist_for(focus, a0 + (a1 - a0) * i / n, e0 + (e1 - e0) * i / n, framing, lens0)[1]
                       for i in range(n + 1))
            dist = best / radius
        return [key(0.0, a0, e0, focus, framing, dist=dist), key(dur, a1, e1, focus, framing, dist=dist)]
    if typ in ('push_in', 'push_out'):
        f0d, f1d = (0.75, 1.6) if typ == 'push_in' else (1.6, 0.75)
        f0 = float(move.get('framing_from', f0d if 'framing' not in move else framing * (f0d / 0.9)))
        f1 = float(move.get('framing_to', f1d))
        fo0 = move.get('focus_from', focus if typ == 'push_in' else move.get('target', focus))
        fo1 = move.get('focus_to', move.get('target', focus) if typ == 'push_in' else focus)
        a0 = float(move.get('azimuth_from', az))
        a1 = float(move.get('azimuth_to', a0 + float(move.get('degrees', 0.0))))
        e0 = float(move.get('elevation_from', el))
        e1 = float(move.get('elevation_to', el))
        return [key(0.0, a0, e0, fo0, f0), key(dur, a1, e1, fo1, f1)]
    if typ == 'reveal':
        a1 = float(move.get('azimuth_to', az))
        a0 = float(move.get('azimuth_from', a1 - float(move.get('degrees', 40.0))))
        e0 = float(move.get('elevation_from', -2.0))
        e1 = float(move.get('elevation_to', el + 8.0))
        f0 = float(move.get('framing_from', 2.4))
        f1 = float(move.get('framing_to', framing))
        return [key(0.0, a0, e0, move.get('focus_from', focus), f0), key(dur, a1, e1, move.get('focus_to', focus), f1)]
    if typ == 'fly_past':
        c, r = subject(focus, objs, dg, center, radius, info)
        side = math.radians(float(move.get('side', 90.0)))
        off = float(move.get('offset', 2.2)) * radius
        hgt = float(move.get('height', 0.15)) * radius
        length = float(move.get('length', 5.0)) * radius
        n = Vector((math.sin(side), -math.cos(side), 0.0))           # from the focus toward the path
        along = Vector((-n.y, n.x, 0.0))
        if move.get('direction', 1) in (-1, 'reverse', 'back'):
            along = -along
        base = c + n * off + Vector((0, 0, hgt))
        p0 = base - along * (length / 2)
        p1 = base + along * (length / 2)
        look = move.get('look', 'focus')
        if look == 'ahead':
            ahead = float(move.get('look_ahead', 1.5)) * radius
            f0 = p0 + along * ahead - n * off * 0.5
            f1 = p1 + along * ahead - n * off * 0.5
            f0.z = f1.z = c.z
        else:
            f0 = f1 = c
        k0 = {'t': 0.0, 'az': 0, 'el': 0, 'dist': 1, 'focus': list(f0), 'lens': lens0, 'roll': roll, 'pos': list(p0)}
        k1 = {'t': dur, 'az': 0, 'el': 0, 'dist': 1, 'focus': list(f1), 'lens': lens0, 'roll': roll, 'pos': list(p1)}
        return [k0, k1]
    raise ValueError(f'unknown move type {typ!r}')


# ------------------------------------------------------------------ render

def setup_engine(job):
    scene = bpy.context.scene
    eng = job.get('engine', 'eevee')
    want = {'eevee': ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'], 'cycles': ['CYCLES'],
            'workbench': ['BLENDER_WORKBENCH']}[eng]
    ok = None
    for w in want:
        try:
            scene.render.engine = w
            ok = w
            break
        except TypeError:
            continue
    if not ok:
        raise RuntimeError(f'engine {eng} not available')
    samples = int(job.get('samples') or 0)
    if eng == 'eevee' and samples:
        for attr in ('taa_render_samples',):
            try:
                setattr(scene.eevee, attr, samples)
            except Exception:
                pass
    if eng == 'cycles':
        scene.cycles.samples = samples or 64
        try:
            scene.cycles.use_denoising = True
        except Exception:
            pass
        dev = job.get('device', 'gpu')
        if dev == 'gpu':
            try:
                prefs = bpy.context.preferences.addons['cycles'].preferences
                for t in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
                    try:
                        prefs.compute_device_type = t
                        prefs.get_devices()
                        if any(d.type == t for d in prefs.devices):
                            for d in prefs.devices:
                                d.use = d.type == t
                            scene.cycles.device = 'GPU'
                            break
                    except Exception:
                        continue
            except Exception as e:
                log('gpu setup failed', e)
    if eng == 'workbench':
        try:
            scene.display.shading.light = 'STUDIO'
            scene.display.shading.color_type = 'MATERIAL'
        except Exception:
            pass
    scene.render.film_transparent = bool(job.get('film_transparent', True))
    try:
        scene.view_settings.view_transform = job.get('view_transform', 'AgX')
    except TypeError:
        try:
            scene.view_settings.view_transform = 'Filmic'
        except TypeError:
            pass
    try:
        scene.view_settings.look = 'None'
    except TypeError:
        pass
    return ok


def project_px(scene, cam, co, w, h):
    from bpy_extras.object_utils import world_to_camera_view
    v = world_to_camera_view(scene, cam, Vector(co))
    return [v.x * w, (1 - v.y) * h, v.z]


def occluded(scene, dg, cam_loc, co, own):
    d = Vector(co) - cam_loc
    dist = d.length
    if dist < 1e-6:
        return False
    hit, loc, nrm, idx, obj, mat = scene.ray_cast(dg, cam_loc, d.normalized(), distance=dist * 0.999)
    return bool(hit) and (obj is None or obj.name not in own)


def render(job):
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [o for o in scene.objects if renderable(o)]
    # hide
    for spec in job.get('hide') or []:
        for o in match_objects(spec, objs):
            o.hide_render = True
    objs = [o for o in objs if not o.hide_render]
    gl = ground_like(objs, dg, job.get('frame_ignore'))
    bb = world_bbox([o for o in objs if o not in gl], dg) or world_bbox(objs, dg)
    if not bb:
        raise RuntimeError('the model has no visible objects')
    lo, hi = bb
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-4)
    info = {'bounds': [list(lo), list(hi)], 'center': list(center), 'radius': radius, 'missing': [],
            'left_out_of_bounds': [o.name for o in gl]}

    # x-ray: everything not shown becomes a ghost
    xr = job.get('xray')
    shown = set()
    if xr:
        for spec in xr.get('show') or []:
            mats = match_materials(spec)
            if mats:
                names = {m.name for m in mats}
                for o in objs:
                    if any(s.material and s.material.name in names for s in o.material_slots):
                        shown.add((o.name, tuple(sorted(names))))
            else:
                found = match_objects(spec, objs)
                if not found:
                    info['missing'].append(spec)
                for o in found:
                    shown.add((o.name, None))
        ghost = ghost_material('render3d xray', hex_rgb(xr.get('color', '#7fc8ff')), xr.get('alpha', 0.04),
                               xr.get('edge', 0.5), xr.get('edge_strength', 1.5))
        whole = {n for n, m in shown if m is None}
        partial = {}
        for n, m in shown:
            if m is not None:
                partial.setdefault(n, set()).update(m)
        for o in objs:
            if o.name in whole or o.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT'):
                continue
            if o.name in partial:
                keep = partial[o.name]
                if not o.material_slots:
                    o.data.materials.append(ghost)
                for s in o.material_slots:
                    if not (s.material and s.material.name in keep):
                        s.material = ghost
            else:
                assign_all(o, ghost)
            o.visible_shadow = False if xr.get('ghost_shadows', False) is False else True
    # highlights
    for i, hl in enumerate(job.get('highlight') or []):
        color = hex_rgb(hl.get('color', '#ffb000'))
        strength = float(hl.get('strength', 2.0))
        mode = hl.get('mode', 'solid')
        mats = match_materials(hl['target'])
        if mats:
            names = {m.name for m in mats}
            cache = {}

            def mk(old, color=color, strength=strength, mode=mode, cache=cache, i=i):
                if old.name not in cache:
                    cache[old.name] = (glow_copy(old, color, strength) if mode == 'glow'
                                       else solid_material(f'render3d highlight {i}', color, strength))
                return cache[old.name]
            for o in objs:
                replace_material(o, names, mk)
            continue
        found = match_objects(hl['target'], objs)
        if not found:
            info['missing'].append(hl['target'])
        solid = solid_material(f'render3d highlight {i}', color, strength) if mode != 'glow' else None
        for o in found:
            if mode == 'glow':
                if not o.material_slots:
                    o.data.materials.append(solid_material(f'render3d highlight {i}', color, strength))
                for s in o.material_slots:
                    if s.material:
                        s.material = glow_copy(s.material, color, strength)
            else:
                assign_all(o, solid)

    # turntable pivot
    move = job['move']
    pivot = None
    if move.get('type') == 'turntable':
        pivot = bpy.data.objects.new('render3d pivot', None)
        scene.collection.objects.link(pivot)
        pivot.location = center
        bpy.context.view_layer.update()
        roots = [o for o in scene.objects if o.parent is None and o is not pivot and o.type not in ('CAMERA', 'LIGHT')]
        for o in roots:
            mw = o.matrix_world.copy()
            o.parent = pivot
            o.matrix_parent_inverse = pivot.matrix_world.inverted()
            o.matrix_world = mw

    # ground
    ground = job.get('ground', 'none')
    if ground and ground != 'none':
        bpy.ops.mesh.primitive_plane_add(size=radius * 30, location=(center.x, center.y, lo.z))
        g = bpy.context.active_object
        g.name = 'render3d ground'
        if ground == 'shadow':
            try:
                g.is_shadow_catcher = True
            except Exception:
                pass
        else:
            g.data.materials.append(solid_material('render3d ground', hex_rgb(ground, (0.5, 0.5, 0.5)), 0.0))

    lighting(job.get('lighting', 'studio'), center, radius, job)
    eng = setup_engine(job)

    # camera
    cd = bpy.data.cameras.new('render3d camera')
    cam = bpy.data.objects.new('render3d camera', cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cd.sensor_width = 36.0
    cd.clip_start = radius * 0.005
    cd.clip_end = radius * 400
    w, h = int(job['width']), int(job['height'])
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    try:
        scene.render.image_settings.color_depth = '8'
    except Exception:
        pass
    keys = compile_move(move, job, center, radius, objs, dg, w / h, info)
    info['keys'] = keys
    easing = job.get('easing', 'ease_in_out')
    fps = float(job['fps'])
    nframes = int(job['frames_total'])
    frames = job.get('frames') or list(range(nframes))
    callouts = job.get('callouts') or []
    anchors = []
    for c in callouts:
        pts = target_points(c['target'], [o for o in scene.objects if o.type in MESHLIKE], dg) if c.get('target') else []
        if c.get('point') is not None:
            p = Vector(c['point'])
        elif pts:
            a, b = bbox_of(pts)
            fr = c.get('anchor', 'center')
            m = (a + b) / 2
            p = {'center': m, 'top': Vector((m.x, m.y, b.z)), 'bottom': Vector((m.x, m.y, a.z)),
                 'front': Vector((m.x, a.y, m.z)), 'back': Vector((m.x, b.y, m.z)),
                 'left': Vector((a.x, m.y, m.z)), 'right': Vector((b.x, m.y, m.z))}.get(fr, m)
            if c.get('offset'):
                p = p + Vector(c['offset'])
        else:
            info['missing'].append(c.get('target'))
            p = None
        anchors.append(p)
    own = {}
    for c in callouts:
        own_names = {o.name for o in match_objects(c.get('target') or '', objs)} if c.get('target') else set()
        own[id(c)] = own_names
    out = job['out_dir']
    per = []
    import time as _t
    t0 = _t.time()
    for k, f in enumerate(frames):
        t = f / fps
        p = pose_at(keys, t, easing)
        loc = cam_location(p)
        cam.location = loc
        look = Vector(p['focus']) - loc
        q = look.to_track_quat('-Z', 'Y')
        cam.rotation_euler = q.to_euler()
        if p.get('roll'):
            cam.rotation_euler.rotate_axis('Z', math.radians(p['roll']))
        cd.lens = p['lens']
        if pivot is not None:
            pivot.rotation_euler = (0, 0, math.radians(move.get('turn_from', 0) +
                                                    (move.get('turn_to', 360) - move.get('turn_from', 0)) *
                                                    ease(t / max(1e-9, job['duration']), move.get('easing', 'linear'))))
        scene.frame_set(int(f) % 1048574 if f >= 0 else 0)
        bpy.context.view_layer.update()
        dg2 = bpy.context.evaluated_depsgraph_get()
        row = {'frame': f, 't': round(t, 4), 'camera': [round(x, 4) for x in loc], 'lens': round(p['lens'], 3),
               'callouts': []}
        rot = pivot.matrix_world if pivot is not None else Matrix.Identity(4)
        piv0 = Matrix.Translation(center) if pivot is not None else None
        for c, a in zip(callouts, anchors):
            if a is None:
                row['callouts'].append(None)
                continue
            wa = a
            if pivot is not None:
                # anchors were measured before rotation, about the pivot at `center`
                wa = rot @ (piv0.inverted() @ a)
            x, y, z = project_px(scene, cam, wa, w, h)
            occ = occluded(scene, dg2, loc, wa, own[id(c)]) if c.get('check_hidden', True) and z > 0 else False
            row['callouts'].append({'x': round(x, 2), 'y': round(y, 2), 'in_front': z > 0, 'hidden': occ})
        scene.render.filepath = os.path.join(out, f'f_{k:05d}.png')
        bpy.ops.render.render(write_still=True)
        per.append(row)
        if k == 0 or k % 10 == 9:
            log(f'frame {k + 1}/{len(frames)} {(_t.time() - t0):.1f}s')
    info.update(engine=eng, frames=per, seconds=round(_t.time() - t0, 2))
    return info


def main():
    job = json.load(open(ARGS[0], encoding='utf-8-sig'))
    out = job['out_dir']
    os.makedirs(out, exist_ok=True)
    try:
        load(job)
        if job['mode'] == 'list':
            res = list_model(job)
            json.dump(res, open(os.path.join(out, 'list.json'), 'w', encoding='utf-8'))
        else:
            res = render(job)
            json.dump(res, open(os.path.join(out, 'frames.json'), 'w', encoding='utf-8'))
    except Exception as e:
        json.dump({'error': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[-3000:]},
                  open(os.path.join(out, 'error.json'), 'w', encoding='utf-8'))
        log('ERROR', e)
        sys.exit(1)


main()
