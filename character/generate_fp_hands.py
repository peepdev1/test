"""
Builds the first-person arms/hands of the red "bean" mascot: the same
open hand (palm + 3 fingers + thumb) as the full body, but placed as a
viewmodel in front of a camera, with its own rig and three pose actions
that match the reference sheet:

    FP_Idle      - relaxed, open, fingers slightly spread
    FP_HoldItem  - palms turned inward, holding a box (Prop_Box)
    FP_PullDrag  - fists gripping a horizontal bar (Prop_Bar)

    python3 generate_fp_hands.py [output_dir] [--no-render]

Output: fp_hands.blend / .glb / .fbx, renders/fp_sheet.png.

Rig: Root (at the camera) > Shoulder.X > UpperArm.X > LowerArm.X > Hand.X
     Hand.X > Index/Middle/Ring.01..03.X, Thumb.01..03.X
The FP_Camera object is parented to the Root bone, so moving Root moves
camera and arms together.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import beanlib as B  # noqa: E402

CAM_POS = Vector((0.0, 0.0, 1.60))
CAM_TILT = 15.0                       # degrees looking down
SHOULDER = Vector((0.37, 0.01, 1.20))  # left; right is mirrored in X
ARM_DIR = Vector((-0.24, -0.92, 0.31))  # left; right is mirrored in X


def fp_frame(side):
    sgn = 1.0 if side == "L" else -1.0
    origin = Vector((sgn * SHOULDER.x, SHOULDER.y, SHOULDER.z))
    A = Vector((sgn * ARM_DIR.x, ARM_DIR.y, ARM_DIR.z))
    return B.ArmFrame(side, origin, A, Vector((0, 0, -1)))


def build(scene):
    col = bpy.data.collections.new("FPHands")
    scene.collection.children.link(col)
    mats = B.materials()

    objs, chains, frames = [], [], {}
    bones = [dict(name="Root", head=tuple(CAM_POS), tail=tuple(CAM_POS + Vector((0, -0.25, 0))))]
    for side in ("L", "R"):
        fr = fp_frame(side)
        frames[side] = fr
        o, b, c = B.build_arm(fr, col, mats["red"], tube_start=-0.30)
        for bd in b:
            if bd["name"].startswith("Shoulder"):
                bd["parent"] = "Root"
        objs += o
        bones += b
        chains += c
    groups = [
        ("Arm.L", lambda n: n.endswith(".L") and n.startswith(("Shoulder", "UpperArm", "LowerArm", "Hand"))),
        ("Arm.R", lambda n: n.endswith(".R") and n.startswith(("Shoulder", "UpperArm", "LowerArm", "Hand"))),
        ("Fingers.L", lambda n: n.endswith(".L") and n.startswith(("Index", "Middle", "Ring", "Thumb"))),
        ("Fingers.R", lambda n: n.endswith(".R") and n.startswith(("Index", "Middle", "Ring", "Thumb"))),
    ]
    arm = B.build_armature("FPHands_Rig", bones, col, groups)
    mesh = B.skin_and_join("FPHands_Mesh", objs, chains, arm, col)

    cam_d = bpy.data.cameras.new("FP_Camera")
    cam_d.lens = 22.0
    cam_d.sensor_width = 36.0
    cam_d.clip_start = 0.02
    cam = bpy.data.objects.new("FP_Camera", cam_d)
    col.objects.link(cam)
    cam.parent = arm
    cam.parent_type = "BONE"
    cam.parent_bone = "Root"
    # bone parenting attaches to the bone *tail*; put the camera back at the head
    cam.matrix_parent_inverse = (arm.matrix_world @ arm.pose.bones["Root"].matrix).inverted()
    # a camera looks down its local -Z: rotate 180 about Z so it faces -Y, then tilt
    cam.matrix_world = (B.Matrix.Translation(CAM_POS) @ B.Matrix.Rotation(math.pi, 4, "Z")
                        @ B.Matrix.Rotation(math.radians(90.0 - CAM_TILT), 4, "X"))
    scene.camera = cam
    return arm, mesh, frames, mats, cam, col


def hand_frame_world(arm, side):
    """Posed Hand bone: (center of palm, palm normal, thumb dir, forward)."""
    pb = arm.pose.bones[f"Hand.{side}"]
    m = arm.matrix_world @ pb.matrix
    fwd = (m.to_3x3() @ Vector((0, 1, 0))).normalized()
    x = (m.to_3x3() @ Vector((1, 0, 0))).normalized()   # = palm normal on L, -palm on R
    palm = x if side == "L" else -x
    thumb = (m.to_3x3() @ Vector((0, 0, 1))).normalized()
    center = m.translation + fwd * 0.07
    return center, palm, thumb, fwd


def make_props(col, mats):
    tan = B.make_material("Prop_Cardboard", (0.55, 0.36, 0.18, 1.0), roughness=0.8)
    grey = B.make_material("Prop_Metal", (0.35, 0.35, 0.36, 1.0), roughness=0.45)
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    box = B.adopt(bpy.context.active_object, "Prop_Box", tan, col)
    for p in box.data.polygons:
        p.use_smooth = False
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.03, depth=1.2)
    bar = B.adopt(bpy.context.active_object, "Prop_Bar", grey, col)
    bar.rotation_euler = (0.0, math.pi / 2, 0.0)
    return box, bar


def make_poses(arm, frames, box, bar):
    L, R = frames["L"], frames["R"]
    acts = {}

    # A. idle: open, relaxed
    rots = {}
    for fr in (L, R):
        B.curl_hand(rots, fr, fingers=(6.0, 9.0, 6.0), thumb=(6.0, 8.0), spread=12.0)
        rots[f"Thumb.01.{fr.side}"] = (10.0, 0.0, 0.0)          # thumb slightly away
    acts["FP_Idle"] = B.make_action(arm, "FP_Idle", rots)

    # B. hold item: forearms pronated so the palms face each other, fingers
    #    curled over the box edge, thumbs on top
    rots = {}
    for fr in (L, R):
        s = fr.side
        rots[f"UpperArm.{s}"] = (-4.0, 0.0, 0.0)
        rots[f"LowerArm.{s}"] = (0.0, fr.curl * 90.0, 0.0)
        rots[f"Hand.{s}"] = (0.0, 0.0, fr.curl * 12.0)
        B.curl_hand(rots, fr, fingers=(12.0, 14.0, 10.0), thumb=(10.0, 12.0), thumb_sweep=8.0, spread=6.0)
    acts["FP_HoldItem"] = B.make_action(arm, "FP_HoldItem", rots)
    cL, pL, tL, fL = hand_frame_world(arm, "L")
    cR, pR, tR, fR = hand_frame_world(arm, "R")
    inner_L = cL + pL * 0.045
    inner_R = cR + pR * 0.045
    width = (inner_L - inner_R).length
    mid = (inner_L + inner_R) / 2.0
    box.scale = (width, 0.40, 0.24)                 # deep enough to cover the finger tips
    box.location = mid + Vector((0.0, -0.16, 0.02))
    box.rotation_euler = (0.0, 0.0, 0.0)

    # C. pull / drag: fists closed around a horizontal bar
    rots = {}
    for fr in (L, R):
        s = fr.side
        rots[f"UpperArm.{s}"] = (14.0, 0.0, 0.0)                 # arms in toward the centre
        rots[f"LowerArm.{s}"] = (-6.0, 0.0, 0.0)
        rots[f"Hand.{s}"] = (0.0, 0.0, fr.curl * -8.0)
        B.curl_hand(rots, fr, fingers=(82.0, 95.0, 65.0), thumb=(40.0, 50.0), thumb_sweep=30.0)
    acts["FP_PullDrag"] = B.make_action(arm, "FP_PullDrag", rots)
    cL, pL, _, _ = hand_frame_world(arm, "L")
    cR, pR, _, _ = hand_frame_world(arm, "R")
    grip = ((cL + pL * 0.035) + (cR + pR * 0.035)) / 2.0
    bar.location = grip
    return acts


def render_sheet(scene, arm, cam, acts, box, bar, out_dir):
    rdir = os.path.join(out_dir, "renders")
    os.makedirs(rdir, exist_ok=True)
    B.setup_render(scene, samples=48, size=(900, 600))
    scene.camera = cam
    files = []
    for name, label, props in (("FP_Idle", "A. first person idle", ()),
                               ("FP_HoldItem", "B. hold item", (box,)),
                               ("FP_PullDrag", "C. pull / drag", (bar,))):
        B.set_action(arm, acts[name])
        box.hide_render = box not in props
        bar.hide_render = bar not in props
        B.clear_lights(scene)
        B.add_light(scene, "Key", "AREA", (1.5, -1.0, 3.2), 500, 2.5, (0, -0.4, 1.35))
        B.add_light(scene, "Fill", "AREA", (-2.0, -1.5, 1.8), 200, 3.0, (0, -0.4, 1.35))
        files.append((label, B.render(scene, os.path.join(rdir, f"{name.lower()}.png"))))
    B.compose_sheet(files, os.path.join(rdir, "fp_sheet.png"))
    box.hide_render = bar.hide_render = False
    B.set_action(arm, acts["FP_Idle"])
    B.clear_lights(scene)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = os.path.abspath(argv[0]) if argv and not argv[0].startswith("--") else os.getcwd()
    do_render = "--no-render" not in argv
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.frame_start, scene.frame_end = 1, 24

    arm, mesh, frames, mats, cam, col = build(scene)
    box, bar = make_props(col, mats)
    acts = make_poses(arm, frames, box, bar)
    B.set_action(arm, acts["FP_Idle"])

    B.export_all([arm, mesh], "fp_hands", out_dir)
    if do_render:
        render_sheet(scene, arm, cam, acts, box, bar, out_dir)
    box.hide_viewport = bar.hide_viewport = True   # props are only for the poses
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "fp_hands.blend"))
    print("done ->", out_dir)
    print("bones:", len(arm.data.bones), "verts:", len(mesh.data.vertices))


if __name__ == "__main__":
    main()
