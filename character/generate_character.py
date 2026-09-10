"""
Procedurally builds the red "bean" mascot character (front/left/back/right
turnaround reference) with Blender's Python API and exports it.

Run with the standalone bpy module or inside Blender:
    python3 generate_character.py [output_dir] [--no-render]
    blender -b -P generate_character.py -- [output_dir] [--no-render]

Coordinate conventions (Blender): Z up, character faces -Y, +X is the
character's own left side. Units are metres; the character is 2.0 m tall
(feet to top of head) so it drops straight into game engines at a sane scale.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------
# reference measurements (px from the reference sheet -> metres)
# --------------------------------------------------------------------------
PX = 2.0 / 475.0                 # total character height 475 px == 2.0 m

BODY_BOTTOM_Z = 0.36             # body sits on top of the stubby legs
BODY_HEIGHT = 390 * PX           # ~1.64 m
BODY_RX = 0.42                   # half width (front view)
BODY_RY = 0.38                   # half depth (side view, slightly slimmer)
CAP_R = 0.40                     # radius of the hemispherical caps
TAPER = 0.16                     # top is ~84 % as wide as the bottom

EYE_R = 0.175
EYE_Z = 2.0 - 80 * PX            # ~1.66 m
EYE_X = 0.19
PUPIL_R = 0.062

MOUTH_Z = 2.0 - 147 * PX         # ~1.38 m
MOUTH_HALF_W = 0.15
MOUTH_X_OFF = 0.04

ARM_Z = 2.0 - 210 * PX           # ~1.12 m (shoulder height)
ARM_R_SHOULDER = 0.085
ARM_R_WRIST = 0.070
ARM_X0 = 0.30                    # starts inside the body
ARM_X1 = 0.96                    # wrist

LEG_X = 0.22
LEG_R = 0.105
FOOT_RADII = (0.15, 0.21, 0.115)    # plump slipper: half width, half length, half height

RED = (0.85, 0.015, 0.012, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK = (0.01, 0.01, 0.01, 1.0)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def make_material(name, color, roughness=0.35, specular=0.5, subsurface=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    if subsurface and "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
        bsdf.inputs["Subsurface Radius"].default_value = (0.2, 0.05, 0.05)
    mat.diffuse_color = color
    return mat


def smooth(ob):
    for p in ob.data.polygons:
        p.use_smooth = True


def finish(ob, name, mat, parent, col):
    ob.name = name
    ob.data.name = name
    ob.data.materials.append(mat)
    smooth(ob)
    ob.parent = parent
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    return ob


def uv_sphere(radius=1.0, location=(0, 0, 0), segments=32, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, radius=radius, location=location
    )
    return bpy.context.active_object


def body_profile(t):
    """Horizontal scale of the body cross-section as a function of height
    t in [0, 1] (0 = bottom, 1 = top). Bean: slightly heavier below the
    middle and tapering toward the top."""
    taper = 1.0 - TAPER * t
    bulge = 1.0 + 0.06 * math.exp(-((t - 0.35) / 0.25) ** 2)
    return taper * bulge


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build(scene):
    col = bpy.data.collections.new("RedBean")
    scene.collection.children.link(col)

    root = bpy.data.objects.new("RedBean", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.5
    col.objects.link(root)

    mat_red = make_material("RedBean_Body", RED, roughness=0.30)
    mat_white = make_material("RedBean_EyeWhite", WHITE, roughness=0.12)
    mat_black = make_material("RedBean_Black", BLACK, roughness=0.25)

    # ---------------- body: stretched + tapered sphere -> bean capsule -----
    body = uv_sphere(1.0, segments=64, rings=48)
    half_len = (BODY_HEIGHT - 2 * CAP_R) / 2.0
    for v in body.data.vertices:
        x, y, z = v.co
        zc = z * CAP_R + math.copysign(half_len, z)          # capsule
        t = (zc + BODY_HEIGHT / 2.0) / BODY_HEIGHT           # 0..1
        s = body_profile(t)
        X = x * BODY_RX * s
        Y = y * BODY_RY * s
        if Y < 0:                                            # belly bulge at the front
            Y *= 1.0 + 0.14 * (1.0 - t) ** 1.6
        v.co = (X, Y, zc + BODY_HEIGHT / 2.0 + BODY_BOTTOM_Z)
    body.data.update()
    finish(body, "Body", mat_red, root, col)

    def surface_y(x, z):
        """Front surface of the body at (x, z) via ray cast."""
        ok, loc, _n, _i = body.ray_cast(Vector((x, -5.0, z)), Vector((0, 1, 0)))
        return loc.y if ok else -BODY_RY

    # ---------------- eyes -----------------------------------------------
    # The reference has the character's right eye (viewer's left, -X)
    # a hair larger and lower - keeps it from looking too symmetric.
    eyes = [("R", -EYE_X, EYE_R * 1.03, EYE_Z - 0.012),
            ("L", +EYE_X, EYE_R * 0.98, EYE_Z + 0.006)]
    for side, ex, er, ez in eyes:
        ys = surface_y(ex, ez)
        ey = ys - er * 0.30                                  # ~2/3 of the eye sticks out
        eye = uv_sphere(er, (ex, ey, ez), segments=48, rings=24)
        finish(eye, f"Eye.{side}", mat_white, root, col)

        # pupil: flattened black disc on the eye surface looking slightly
        # to the viewer's right and down, like the reference
        look = Vector((0.18, -1.0, -0.22)).normalized()
        pupil = uv_sphere(PUPIL_R, tuple(Vector((ex, ey, ez)) + look * (er * 0.93)),
                          segments=32, rings=16)
        pupil.rotation_euler = look.to_track_quat("-Y", "Z").to_euler()
        pupil.scale = (1.0, 0.35, 1.0)
        finish(pupil, f"Pupil.{side}", mat_black, root, col)

    # ---------------- mouth: small flat, slightly sad line ---------------
    curve = bpy.data.curves.new("Mouth", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.011
    curve.bevel_resolution = 4
    curve.resolution_u = 16
    curve.use_fill_caps = True
    spline = curve.splines.new("BEZIER")
    xs = [-1.0, -0.5, 0.0, 0.5, 1.0]
    spline.bezier_points.add(len(xs) - 1)
    for bp, u in zip(spline.bezier_points, xs):
        x = MOUTH_X_OFF + u * MOUTH_HALF_W
        z = MOUTH_Z + 0.012 - 0.024 * u * u                  # ends droop
        y = surface_y(x, z) - 0.001
        bp.co = (x, y, z)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    mouth = bpy.data.objects.new("Mouth", curve)
    col.objects.link(mouth)
    bpy.context.view_layer.objects.active = mouth
    mouth.select_set(True)
    bpy.ops.object.convert(target="MESH")
    mouth = bpy.context.active_object
    finish(mouth, "Mouth", mat_black, root, col)

    # ---------------- arms + fists (T-pose) ------------------------------
    for side, sgn in (("L", 1.0), ("R", -1.0)):
        length = ARM_X1 - ARM_X0
        bpy.ops.mesh.primitive_cone_add(
            vertices=48, radius1=ARM_R_SHOULDER, radius2=ARM_R_WRIST, depth=length,
            location=(sgn * (ARM_X0 + length / 2.0), 0.0, ARM_Z),
            rotation=(0.0, sgn * math.pi / 2.0, 0.0),
        )
        finish(bpy.context.active_object, f"Arm.{side}", mat_red, root, col)

        shoulder = uv_sphere(ARM_R_SHOULDER * 1.05, (sgn * (ARM_X0 + 0.05), 0.0, ARM_Z))
        finish(shoulder, f"Shoulder.{side}", mat_red, root, col)

        # fist: palm ellipsoid + 3 knuckle bumps + thumb on top
        px_ = sgn * (ARM_X1 + 0.09)
        palm = uv_sphere(1.0, (px_, -0.01, ARM_Z - 0.01), segments=32, rings=16)
        palm.scale = (0.135, 0.115, 0.125)
        finish(palm, f"Hand.{side}", mat_red, root, col)

        for i, dz in enumerate((0.07, 0.0, -0.07)):
            k = uv_sphere(1.0, (sgn * (ARM_X1 + 0.19), -0.055, ARM_Z - 0.015 + dz),
                          segments=24, rings=12)
            k.scale = (0.055, 0.050, 0.045)
            finish(k, f"Finger{i + 1}.{side}", mat_red, root, col)

        thumb = uv_sphere(1.0, (sgn * (ARM_X1 + 0.08), -0.08, ARM_Z + 0.095),
                          segments=24, rings=12)
        thumb.scale = (0.055, 0.055, 0.048)
        finish(thumb, f"Thumb.{side}", mat_red, root, col)

    # ---------------- legs + feet ----------------------------------------
    # Leg: a tube that runs down from inside the body, narrows at the ankle
    # and curves gently forward into the shoe. Shoe: a plump rounded slipper,
    # wider and thicker than the leg, heel tucked under the leg, toe rounded
    # and sloping down, flat sole on the ground.
    for side, sgn in (("L", 1.0), ("R", -1.0)):
        lx = sgn * LEG_X
        curve = bpy.data.curves.new(f"Leg.{side}", "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = LEG_R
        curve.bevel_resolution = 10
        curve.resolution_u = 24
        curve.use_fill_caps = True
        spline = curve.splines.new("BEZIER")
        pts = [  # (x, y, z, radius multiplier)
            (lx, 0.03, 0.60, 1.00),          # hidden inside the body
            (lx, 0.03, 0.42, 1.00),          # hip
            (lx, 0.01, 0.22, 0.85),          # ankle (thinnest)
            (lx, -0.05, 0.09, 0.90),         # dives into the shoe
        ]
        spline.bezier_points.add(len(pts) - 1)
        for bp, (x, y, z, r) in zip(spline.bezier_points, pts):
            bp.co = (x, y, z)
            bp.radius = r
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        leg = bpy.data.objects.new(f"Leg.{side}", curve)
        col.objects.link(leg)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = leg
        leg.select_set(True)
        bpy.ops.object.convert(target="MESH")
        finish(bpy.context.active_object, f"Leg.{side}", mat_red, root, col)

        foot = uv_sphere(1.0, (0, 0, 0), segments=48, rings=24)
        rx, ry, rz = FOOT_RADII
        for v in foot.data.vertices:
            x, y, z = v.co
            if y < 0:                                     # toe half: full length
                yy = y * ry
                z = z * (1.0 - 0.22 * (-y))               # top slopes down to the toe
            else:                                         # heel half: tucked under the leg
                yy = y * ry * 0.55
            v.co = (x * rx, yy, max(z * rz, -0.02))       # flat sole
        foot.data.update()
        foot.location = (lx, -0.11, 0.095)                # sole rests on z = 0
        finish(foot, f"Foot.{side}", mat_red, root, col)

    # subdivision keeps the primitive shapes soft under close-ups
    for ob in col.objects:
        if ob.type == "MESH" and ob.name.startswith(("Hand", "Finger", "Thumb", "Shoulder")):
            mod = ob.modifiers.new("Subdivision", "SUBSURF")
            mod.levels = 1
            mod.render_levels = 2
    return col


# --------------------------------------------------------------------------
# turnaround render (Cycles CPU) - used to check the build against the sheet
# --------------------------------------------------------------------------
def render_turnaround(scene, out_dir, samples=64):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 600
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"   # keep the red saturated

    world = bpy.data.worlds.new("Grey")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.42, 0.42, 0.42, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    def add_light(name, kind, loc, energy, size=2.0):
        ld = bpy.data.lights.new(name, kind)
        ld.energy = energy
        if kind == "AREA":
            ld.size = size
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        lo.rotation_euler = (Vector(loc) - Vector((0, 0, 1.0))).to_track_quat("Z", "Y").to_euler()
        scene.collection.objects.link(lo)
        return lo

    cam_d = bpy.data.cameras.new("TurnCam")
    cam_d.type = "ORTHO"
    cam_d.ortho_scale = 3.0
    cam = bpy.data.objects.new("TurnCam", cam_d)
    scene.collection.objects.link(cam)
    scene.camera = cam

    views = [("front", (0, -10, 1.0), (math.pi / 2, 0, 0)),
             ("left", (10, 0, 1.0), (math.pi / 2, 0, math.pi / 2)),
             ("back", (0, 10, 1.0), (math.pi / 2, 0, math.pi)),
             ("right", (-10, 0, 1.0), (math.pi / 2, 0, -math.pi / 2))]
    files = []
    for name, loc, rot in views:
        # key/fill lights ride along with the camera so every view reads the same
        for o in [o for o in scene.collection.objects if o.type == "LIGHT"]:
            bpy.data.objects.remove(o)
        v = Vector(loc).normalized()
        right = v.cross(Vector((0, 0, 1))).normalized()
        add_light("Key", "AREA", tuple(v * 5 + right * -3 + Vector((0, 0, 4))), 450, 3)
        add_light("Fill", "AREA", tuple(v * 5 + right * 3 + Vector((0, 0, 1))), 160, 4)
        cam.location = loc
        cam.rotation_euler = rot
        path = os.path.join(out_dir, f"view_{name}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        files.append((name, path))
    return files


def compose_sheet(files, out_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    imgs = [Image.open(p).convert("RGB") for _, p in files]
    w, h = imgs[0].size
    label_h = 70
    sheet = Image.new("RGB", (w * len(imgs), h + label_h), (107, 107, 107))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    for i, ((name, _), im) in enumerate(zip(files, imgs)):
        sheet.paste(im, (i * w, 0))
        txt = name.upper()
        tw = draw.textlength(txt, font=font)
        draw.text((i * w + (w - tw) / 2, h + 12), txt, fill=(20, 20, 20), font=font)
    sheet.save(out_path)
    return out_path


# --------------------------------------------------------------------------
def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = os.path.abspath(argv[0]) if argv and not argv[0].startswith("--") else os.getcwd()
    do_render = "--no-render" not in argv
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    build(scene)

    for ob in bpy.data.objects:
        ob.select_set(ob.name.startswith(("RedBean", "Body", "Eye", "Pupil", "Mouth", "Arm",
                                           "Shoulder", "Hand", "Finger", "Thumb", "Leg", "Foot")))

    bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "red_bean.glb"),
                              export_format="GLB", use_selection=True, export_apply=True)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out_dir, "red_bean.fbx"),
                             use_selection=True, use_mesh_modifiers=True)
    bpy.ops.wm.obj_export(filepath=os.path.join(out_dir, "red_bean.obj"),
                          export_selected_objects=True, apply_modifiers=True,
                          export_materials=True)

    if do_render:
        rdir = os.path.join(out_dir, "renders")
        os.makedirs(rdir, exist_ok=True)
        files = render_turnaround(scene, rdir)
        compose_sheet(files, os.path.join(rdir, "turnaround.png"))

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "red_bean.blend"))
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
