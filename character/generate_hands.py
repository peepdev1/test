"""
Builds the red cartoon glove hands of the mascot as two separate, rigged
objects that match the hand reference sheet:

    Hand_R + Hand_R_Rig   - right hand mesh and its armature
    Hand_L + Hand_L_Rig   - left hand (exact mirror of the right one)

Each hand is one mesh: a cuff (bevelled cylinder) + the glove (plump palm,
three clearly separate fingers and a thumb, all slightly curled). The glove
is built from overlapping primitives (ellipsoids and capsules) that a voxel
remesh fuses into one even quad mesh; the fingers are spaced so they stay
separate digits with a gap between them.

Rig per hand (14 bones):
    Wrist > Hand > Index.01-03 / Middle.01-03 / Ring.01-03 / Thumb.01-03
Every vertex follows the bone chain it is closest to, so each finger bends
on its own. Actions: Rest, Open, Fist, Point.

    python3 generate_hands.py [output_dir] [--no-render]

Output: hands.blend / .glb / .fbx / .obj, renders/hands_sheet.png,
renders/hands_rig.png, renders/hands_poses.png.

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
    ((0.0, 0.000, -0.068), (0.100, 0.052, 0.072)),   # main mitt (wider at the bottom, see PALM_TAPER)
    ((0.0, 0.003, -0.108), (0.098, 0.046, 0.030)),   # knuckle bulge the fingers hang from
]
PALM_TAPER = 0.16                    # the mitt is this much narrower at the top than at the bottom
FINGER_R = (0.029, 0.027, 0.025)     # radius at the base / middle / tip joint
FINGER_SEG = 0.045                   # length of one finger segment (3 per finger)
FINGERS = [                          # (name, x of the base, spread angle in the xz plane)
    ("Index",  +0.074, +14.0),       # thumb-side finger
    ("Middle",  0.000,   0.0),
    ("Ring",   -0.074, -14.0),       # little-finger side
]
FINGER_BASE_Z = -0.122
FINGER_CURL = (6.0, 14.0, 22.0)      # degrees each segment bends toward the palm

THUMB_BASE = (0.074, -0.002, -0.080)
THUMB_R = (0.035, 0.032, 0.029)
THUMB_SEG = 0.036
THUMB_OUT = 32.0                     # first segment angle away from the fingers
THUMB_CURL = (0.0, 16.0, 26.0)       # bend toward the palm per segment
THUMB_SWEEP = (0.0, 12.0, 18.0)      # bend back toward the fingers per segment

VOXEL = 0.0028
SMOOTH_ITER = 2
BLEND_HAND = 0.012                   # weight blend radius around finger joints
BLEND_WRIST = 0.02


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


def digits():
    """{name: [joint points]} of the right hand in rest pose (4 points each,
    the first one at the base inside the palm)."""
    out = {}
    for name, x, spread in FINGERS:
        d0 = Matrix.Rotation(math.radians(spread), 3, "Y") @ Vector((0, 0, -1))
        out[name] = digit_points((x, 0.003, FINGER_BASE_Z), d0, FINGER_SEG,
                                 [(c, 0.0) for c in FINGER_CURL])
    d0 = Matrix.Rotation(math.radians(-THUMB_OUT), 3, "Y") @ Vector((0, 0, -1))   # toward +X
    out["Thumb"] = digit_points(THUMB_BASE, d0, THUMB_SEG, list(zip(THUMB_CURL, THUMB_SWEEP)))
    return out


def glove_parts(name, col, mat):
    """Palm + fingers + thumb as overlapping closed primitives."""
    objs = []

    def taper(x, y, z):                 # z = +1 at the top of the ellipsoid
        return x * (1.0 - PALM_TAPER * z), y * (1.0 - PALM_TAPER * 0.5 * z), z
    for i, (centre, radii) in enumerate(PALM):
        objs.append(B.ellipsoid(f"{name}_palm{i}", centre, radii, col, mat, segments=48, rings=32,
                                shape=taper if i == 0 else None))
    for dname, pts in digits().items():
        pts = list(pts)
        d0 = (pts[1] - pts[0]).normalized()
        pts[0] = pts[0] - d0 * (0.035 if dname == "Thumb" else 0.03)   # sink the root into the palm
        radii = THUMB_R if dname == "Thumb" else FINGER_R
        objs += digit(f"{name}_{dname}", pts, radii + (radii[-1],), col, mat)
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


# --------------------------------------------------------------------------
# rig
# --------------------------------------------------------------------------
def hand_bones_and_chains(side):
    """Bone specs + weight chains for one hand at the origin.
    Fingers point -Z; local bone Z points to the thumb side, so curling a
    finger is a rotation about local Z (+ on the right hand, - on the left)."""
    sgn = 1.0 if side == "R" else -1.0
    M = Vector((sgn, 1.0, 1.0))

    def P(v):
        return Vector((v[0] * M.x, v[1] * M.y, v[2] * M.z))

    thumb_dir = Vector((sgn, 0, 0))
    wrist_top, wrist, knuckles = P((0, 0, CUFF_TOP)), P((0, 0, 0)), P((0, 0.003, FINGER_BASE_Z))
    bones = [
        dict(name="Wrist", head=wrist_top, tail=wrist, roll=thumb_dir),
        dict(name="Hand", head=wrist, tail=knuckles, parent="Wrist", roll=thumb_dir, connect=True),
    ]
    chains = []
    for dname, pts in digits().items():
        pts = [P(p) for p in pts]
        roll = Vector((0, 1, 0)) if dname == "Thumb" else thumb_dir   # thumb curls toward +Y (palm)
        chain = [("Wrist", wrist_top, wrist), ("Hand", wrist, pts[0])]
        parent = "Hand"
        for k in range(3):
            bname = f"{dname}.{k + 1:02d}"
            bones.append(dict(name=bname, head=pts[k], tail=pts[k + 1], parent=parent, roll=roll,
                              connect=k > 0))
            chain.append((bname, pts[k], pts[k + 1]))
            parent = bname
        chains.append((chain, BLEND_HAND))
    return bones, chains


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

    bones, chains = hand_bones_and_chains(side)
    groups = [("Hand", lambda n: n in ("Wrist", "Hand")),
              ("Fingers", lambda n: n.startswith(("Index", "Middle", "Ring", "Thumb")))]
    arm = B.build_armature(f"{name}_Rig", bones, col, groups)
    B.nearest_chain_weights(hand, chains)
    mod = hand.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    hand.parent = arm
    return arm, hand


def curl_sign(side):
    return 1.0 if side == "R" else -1.0


def hand_pose(side, fingers=(0, 0, 0), thumb=(0, 0, 0), thumb_sweep=0.0, spread=0.0,
              per_finger=None):
    """Bone rotations (degrees) for one hand.
    fingers: curl per joint (about local Z, sign handled per side);
    thumb: flex per joint toward the palm (thumb bones have local Z = palm
    normal, so flexing is a rotation about local X, same sign both sides);
    thumb_sweep: swing the whole thumb toward the fingers;
    spread: fan the outer fingers; per_finger: {name: curls} overrides."""
    c = curl_sign(side)
    rots = {}
    spread_by = {"Index": +spread, "Middle": 0.0, "Ring": -spread}
    for dname, _, _ in FINGERS:
        curls = (per_finger or {}).get(dname, fingers)
        for k, a in enumerate(curls, start=1):
            rots[f"{dname}.{k:02d}"] = (spread_by[dname] if k == 1 else 0.0, 0.0, c * a)
    for k, a in enumerate(thumb, start=1):
        rots[f"Thumb.{k:02d}"] = (a, 0.0, c * thumb_sweep if k == 1 else 0.0)
    return rots


def make_poses(arms):
    """Same action names on both hands (bone names match, so one action
    drives either armature)."""
    acts = {}
    for side, arm in arms:
        a = {}
        a["Rest"] = B.make_action(arm, f"Rest.{side}", {})
        a["Open"] = B.make_action(arm, f"Open.{side}", hand_pose(
            side, fingers=tuple(-x for x in FINGER_CURL), thumb=(0, -10, -16), spread=6.0))
        a["Fist"] = B.make_action(arm, f"Fist.{side}", hand_pose(
            side, fingers=(70.0, 80.0, 50.0), thumb=(25.0, 40.0, 35.0), thumb_sweep=20.0))
        a["Point"] = B.make_action(arm, f"Point.{side}", hand_pose(
            side, fingers=(70.0, 80.0, 50.0), thumb=(10.0, 25.0, 20.0), thumb_sweep=10.0,
            per_finger={"Index": tuple(-x for x in FINGER_CURL)}))
        B.stash_actions(arm, a.values())
        acts[side] = a
    return acts


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


def aim(cam, loc, centre):
    loc = Vector(loc)
    cam.location = centre + loc
    cam.rotation_euler = (-loc).to_track_quat("-Z", "Y").to_euler()


def render_sheets(scene, hands, acts, mat, out_dir):
    rdir = os.path.join(out_dir, "renders")
    os.makedirs(rdir, exist_ok=True)
    B.setup_render(scene, samples=40, size=(420, 460))
    cam = B.ortho_camera(scene, "HandCam", scale=0.42)
    centre = Vector((0.0, 0.0, -0.088))

    def solo(hand):
        for _, _, other in hands:
            other.hide_render = other is not hand

    rows = []
    for side, arm, hand in hands:
        solo(hand)
        B.set_action(arm, acts[side]["Rest"])
        files = []
        for name, loc, _ in views_for(side):
            aim(cam, loc, centre)
            B.light_from(scene, loc, centre, key=380, fill=140)
            files.append((name, B.render(scene, os.path.join(rdir, f"hand_{side.lower()}_{name}.png"))))
        rows.append((side, files))
    compose_two_rows(rows, os.path.join(rdir, "hands_sheet.png"))

    # rig: bones through a transparent hand, back and palm view
    rows = []
    for side, arm, hand in hands:
        solo(hand)
        B.set_action(arm, acts[side]["Rest"])
        viz = B.bone_viz(scene, arm)
        B.set_alpha([mat], 0.30)
        files = []
        for name, loc, _ in views_for(side)[:3]:
            aim(cam, loc, centre)
            B.light_from(scene, loc, centre, key=380, fill=140)
            files.append((name, B.render(scene, os.path.join(rdir, f"hand_{side.lower()}_rig_{name}.png"))))
        B.set_alpha([mat], 1.0)
        B.remove_collection(viz)
        rows.append((side, files))
    compose_two_rows(rows, os.path.join(rdir, "hands_rig.png"), subtitle="(14 bones)")

    # poses
    rows = []
    for side, arm, hand in hands:
        solo(hand)
        files = []
        for pname in ("Rest", "Open", "Fist", "Point"):
            B.set_action(arm, acts[side][pname])
            for name, loc, _ in views_for(side)[:1] + views_for(side)[2:3]:
                aim(cam, loc, centre)
                B.light_from(scene, loc, centre, key=380, fill=140)
                files.append((f"{pname} {name}", B.render(
                    scene, os.path.join(rdir, f"hand_{side.lower()}_pose_{pname.lower()}_{name}.png"))))
        B.set_action(arm, acts[side]["Rest"])
        rows.append((side, files))
    compose_two_rows(rows, os.path.join(rdir, "hands_poses.png"), subtitle="(actions)")
    for _, _, hand in hands:
        hand.hide_render = False
    B.clear_lights(scene)


def compose_two_rows(rows, out_path, label_h=60, title_h=90, bg=(107, 107, 107),
                     subtitle="(separate object)"):
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
        draw.text((32, y0 + 60), subtitle, fill=(20, 20, 20), font=small)
        for i, ((name, _), im) in enumerate(zip(files, imgs[side])):
            sheet.paste(im, (i * w, y0 + title_h))
            txt = name.upper()
            tw = draw.textlength(txt, font=small)
            draw.text((i * w + (w - tw) / 2, y0 + title_h + h + 10), txt, fill=(20, 20, 20), font=small)
    sheet.save(out_path)
    return out_path


def export_all(hands, out_dir):
    objs = [o for _, arm, hand in hands for o in (arm, hand)]
    B.export_all(objs, "hands", out_dir)
    bpy.ops.object.select_all(action="DESELECT")
    for _, _, hand in hands:
        hand.select_set(True)
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
    scene.frame_start, scene.frame_end = 1, 24

    col = bpy.data.collections.new("Hands")
    scene.collection.children.link(col)
    mat = B.make_material("Hand_Red", B.RED, roughness=0.30)

    hands = []
    for side in ("R", "L"):
        arm, hand = build_hand(side, col, mat)
        hands.append((side, arm, hand))
    acts = make_poses([(s, a) for s, a, _ in hands])
    for side, arm, _ in hands:
        B.set_action(arm, acts[side]["Rest"])

    def place(x_r):
        hands[0][1].location = (-x_r, 0, 0)     # right hand on the character's right (-X)
        hands[1][1].location = (+x_r, 0, 0)
        bpy.context.view_layer.update()

    place(0.35)
    export_all(hands, out_dir)
    if do_render:
        place(0.0)                               # render each hand at the origin
        render_sheets(scene, hands, acts, mat, out_dir)
        place(0.35)
    for o in list(scene.collection.objects):
        if o.type in ("CAMERA", "LIGHT"):
            bpy.data.objects.remove(o)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "hands.blend"))
    for side, arm, h in hands:
        print(f"Hand_{side}: {len(h.data.vertices)} verts, {len(h.data.polygons)} faces, "
              f"{len(arm.data.bones)} bones, {len(h.vertex_groups)} groups")
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
