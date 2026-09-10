"""
Builds the red cartoon glove hands of the mascot as two separate, static
mesh objects that match the hand reference sheet:

    Hand_R  - right hand
    Hand_L  - left hand (exact mirror of the right one)

Each hand is one mesh: a cuff (bevelled cylinder) + the glove itself
(plump palm, three fingers and a thumb, all slightly curled). The glove is
built from overlapping primitives (ellipsoids and capsules) that a voxel
remesh fuses into one even quad mesh, smoothed so the fingers blend into
the palm.

    python3 generate_hands.py [output_dir] [--no-render]

Output: hands.blend / .glb / .fbx / .obj, renders/hands_sheet.png.

Conventions (same as the rest of the character): metres, Z up, the mascot
faces -Y. Both hands are built in the rest pose of a character standing with
the arms down: the cuff on top, the fingers pointing down (-Z), the back of
the hand facing the viewer (-Y), the palm facing +Y and the thumb pointing
toward the body (+X on the right hand, -X on the left hand). The object
origin is the wrist, i.e. the centre of the seam between cuff and glove.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import beanlib as B  # noqa: E402

# --------------------------------------------------------------------------
# measurements (metres; the whole hand is ~0.30 m from cuff top to finger tip)
# --------------------------------------------------------------------------
CUFF_R = 0.062
CUFF_TOP = 0.072            # z of the top of the cuff
CUFF_BOTTOM = -0.014        # sunk a little into the glove
CUFF_BEVEL = 0.013

PALM = [                     # (centre, radii) ellipsoids
    ((0.0, 0.000, -0.068), (0.098, 0.052, 0.072)),   # main mitt (wider at the bottom, see PALM_TAPER)
    ((0.0, 0.003, -0.108), (0.094, 0.046, 0.034)),   # knuckle bulge the fingers hang from
]
PALM_TAPER = 0.16                    # the mitt is this much narrower at the top than at the bottom
FINGER_R = (0.031, 0.029, 0.027)     # radius at the base / middle / tip joint
FINGER_SEG = 0.043                   # length of one finger segment (3 per finger)
FINGERS = [                          # (x of the base, spread angle in the xz plane)
    (+0.067, +13.0),                 # thumb-side finger
    (0.000, 0.0),                    # middle
    (-0.067, -13.0),                 # little-finger side
]
FINGER_BASE_Z = -0.125
FINGER_CURL = (6.0, 14.0, 22.0)      # degrees each segment bends toward the palm

THUMB_BASE = (0.072, -0.002, -0.082)
THUMB_R = (0.036, 0.033, 0.030)
THUMB_SEG = 0.035
THUMB_OUT = 30.0                     # first segment angle away from the fingers
THUMB_CURL = (0.0, 16.0, 26.0)       # bend toward the palm per segment
THUMB_SWEEP = (0.0, 12.0, 18.0)      # bend back toward the fingers per segment

VOXEL = 0.0028
SMOOTH_ITER = 3


def digit_points(base, direction, seg_len, bends):
    """Joint points of a digit: start at `base` going along `direction`, each
    segment rotated by bends[k] = (curl about +X toward the palm, sweep
    about +Y back toward the fingers) relative to the previous one."""
    pts = [Vector(base)]
    d = Vector(direction).normalized()
    for curl, sweep in bends:
        d = Matrix.Rotation(math.radians(curl), 3, "X") @ d
        d = Matrix.Rotation(math.radians(sweep), 3, "Y") @ d
        d.normalize()
        pts.append(pts[-1] + d * seg_len)
    return pts


def digit(name, pts, radii, col, mat):
    """One bent digit = overlapping capsules, one per segment."""
    objs = []
    for k in range(len(pts) - 1):
        objs.append(B.capsule(f"{name}_{k}", pts[k], pts[k + 1], radii[k], radii[k + 1],
                              col, mat, segments=24, rings=24))
    return objs


def glove_parts(name, col, mat):
    """Palm + fingers + thumb as overlapping closed primitives."""
    objs = []
    def taper(x, y, z):                 # z = +1 at the top of the ellipsoid
        return x * (1.0 - PALM_TAPER * z), y * (1.0 - PALM_TAPER * 0.5 * z), z
    for i, (centre, radii) in enumerate(PALM):
        objs.append(B.ellipsoid(f"{name}_palm{i}", centre, radii, col, mat, segments=48, rings=32,
                                shape=taper if i == 0 else None))
    for i, (x, spread) in enumerate(FINGERS):
        d0 = Matrix.Rotation(math.radians(spread), 3, "Y") @ Vector((0, 0, -1))
        pts = digit_points((x, 0.003, FINGER_BASE_Z), d0, FINGER_SEG,
                           [(c, 0.0) for c in FINGER_CURL])
        pts[0] = pts[0] - d0 * 0.03          # sink the root into the palm
        objs += digit(f"{name}_finger{i}", pts, FINGER_R + (FINGER_R[-1],), col, mat)
    d0 = Matrix.Rotation(math.radians(-THUMB_OUT), 3, "Y") @ Vector((0, 0, -1))   # toward +X
    pts = digit_points(THUMB_BASE, d0, THUMB_SEG, list(zip(THUMB_CURL, THUMB_SWEEP)))
    pts[0] = pts[0] - d0 * 0.035
    objs += digit(f"{name}_thumb", pts, THUMB_R + (THUMB_R[-1],), col, mat)
    return objs


def apply_modifier(ob, mod):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)


def remesh_and_smooth(ob):
    rm = ob.modifiers.new("Remesh", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = VOXEL
    rm.use_smooth_shade = True
    apply_modifier(ob, rm)
    sm = ob.modifiers.new("Smooth", "SMOOTH")
    sm.factor = 1.0
    sm.iterations = SMOOTH_ITER
    apply_modifier(ob, sm)
    for p in ob.data.polygons:
        p.use_smooth = True


def make_cuff(name, col, mat):
    depth = CUFF_TOP - CUFF_BOTTOM
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=CUFF_R, depth=depth,
                                        location=(0, 0, (CUFF_TOP + CUFF_BOTTOM) / 2.0))
    ob = B.adopt(bpy.context.active_object, name, mat, col)
    bv = ob.modifiers.new("Bevel", "BEVEL")
    bv.width = CUFF_BEVEL
    bv.segments = 10
    bv.limit_method = "ANGLE"
    bv.angle_limit = math.radians(60)
    apply_modifier(ob, bv)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def join(target, others):
    bpy.ops.object.select_all(action="DESELECT")
    for o in others:
        o.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()
    return target


def mirror_x(ob):
    ob.data.transform(Matrix.Scale(-1.0, 4, Vector((1, 0, 0))))
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def build_hand(side, col, mat):
    name = f"Hand_{side}"
    parts = glove_parts(name, col, mat)
    glove = join(parts[0], parts[1:])
    glove.name = glove.data.name = name
    remesh_and_smooth(glove)          # voxel remesh = union of all the parts
    cuff = make_cuff(f"{name}_cuff", col, mat)
    hand = join(glove, [cuff])
    if side == "L":
        mirror_x(hand)
    hand.location = (0, 0, 0)
    return hand


# --------------------------------------------------------------------------
# renders: the same 6 views per hand as the reference sheet
# --------------------------------------------------------------------------
def views_for(side):
    s = 1.0 if side == "R" else -1.0          # thumb side
    D = 10.0
    return [
        ("front", (0, -D, 0), (0, 0, 0)),                    # back of the hand toward the viewer
        ("side", (s * D, 0, 0), (0, 0, 0)),                  # from the thumb side
        ("back", (0, D, 0), (0, 0, 0)),                      # palm straight on
        ("inner", (-s * D * 0.7, D * 0.6, -D * 0.4), (0, 0, 0)),  # palm, 3/4 from below
        ("top", (0, 0, D), (0, -0.001, 0)),
        ("bottom", (0, 0, -D), (0, 0.001, 0)),
    ]


def render_sheet(scene, hands, out_dir):
    rdir = os.path.join(out_dir, "renders")
    os.makedirs(rdir, exist_ok=True)
    B.setup_render(scene, samples=40, size=(420, 460))
    cam = B.ortho_camera(scene, "HandCam", scale=0.42)
    centre = Vector((0.0, 0.0, -0.088))
    rows = []
    for side, hand in hands:
        for _, other in hands:
            other.hide_render = other is not hand
        files = []
        for name, loc, _ in views_for(side):
            loc = Vector(loc)
            cam.location = centre + loc
            cam.rotation_euler = (-loc).to_track_quat("-Z", "Y").to_euler()
            B.light_from(scene, loc, centre, key=380, fill=140)
            files.append((name, B.render(scene, os.path.join(rdir, f"hand_{side.lower()}_{name}.png"))))
        rows.append((side, files))
    for _, hand in hands:
        hand.hide_render = False
    compose_two_rows(rows, os.path.join(rdir, "hands_sheet.png"))
    B.clear_lights(scene)


def compose_two_rows(rows, out_path, label_h=60, title_h=90, bg=(107, 107, 107)):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    imgs = {side: [Image.open(p).convert("RGB") for _, p in files] for side, files in rows}
    w, h = next(iter(imgs.values()))[0].size
    n = len(rows[0][1])
    row_h = title_h + h + label_h
    sheet = Image.new("RGB", (w * n, row_h * len(rows)), bg)
    draw = ImageDraw.Draw(sheet)
    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except OSError:
        big = small = ImageFont.load_default()
    for r, (side, files) in enumerate(rows):
        y0 = r * row_h
        title = {"R": "RIGHT HAND", "L": "LEFT HAND"}[side]
        draw.text((24, y0 + 14), title, fill=(20, 20, 20), font=big)
        draw.text((32, y0 + 60), "(separate object)", fill=(20, 20, 20), font=small)
        for i, ((name, _), im) in enumerate(zip(files, imgs[side])):
            sheet.paste(im, (i * w, y0 + title_h))
            txt = name.upper()
            tw = draw.textlength(txt, font=small)
            draw.text((i * w + (w - tw) / 2, y0 + title_h + h + 10), txt, fill=(20, 20, 20), font=small)
    sheet.save(out_path)
    return out_path


def export_all(hands, out_dir):
    objs = [h for _, h in hands]
    B.export_all(objs, "hands", out_dir)
    bpy.ops.wm.obj_export(filepath=os.path.join(out_dir, "hands.obj"),
                          export_selected_objects=True, export_materials=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = os.path.abspath(argv[0]) if argv and not argv[0].startswith("--") else os.getcwd()
    do_render = "--no-render" not in argv
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"

    col = bpy.data.collections.new("Hands")
    scene.collection.children.link(col)
    mat = B.make_material("Hand_Red", B.RED, roughness=0.30)

    hands = [(side, build_hand(side, col, mat)) for side in ("R", "L")]
    hands[0][1].location = (-0.35, 0, 0)     # right hand on the character's right (-X)
    hands[1][1].location = (+0.35, 0, 0)

    export_all(hands, out_dir)
    if do_render:
        # render each hand at the origin, then put them back side by side
        for _, h in hands:
            h.location = (0, 0, 0)
        render_sheet(scene, hands, out_dir)
        hands[0][1].location = (-0.35, 0, 0)
        hands[1][1].location = (+0.35, 0, 0)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "hands.blend"))
    for side, h in hands:
        print(f"Hand_{side}: {len(h.data.vertices)} verts, {len(h.data.polygons)} faces")
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
