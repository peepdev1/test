"""
Builds the rigged red "bean" mascot (full body) with Blender's Python API,
exports it and renders check sheets.

    python3 generate_character.py [output_dir] [--no-render]
    blender -b -P generate_character.py -- [output_dir] [--no-render]

Output: red_bean.blend / .glb / .fbx / .obj, renders/turnaround.png,
renders/rig.png, renders/poses.png.

Rig (Z up, T-pose rest, faces -Y, +X = character's left):
    Root > Hips > Spine > Chest > Head > Eye.L / Eye.R
    Chest > Shoulder.X > UpperArm.X > LowerArm.X > Hand.X
    Hand.X > Index/Middle/Ring.01..03.X, Thumb.01..03.X
    Hips  > UpperLeg.X > LowerLeg.X > Foot.X > Toe.X
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import beanlib as B  # noqa: E402


def build(scene):
    col = bpy.data.collections.new("RedBean")
    scene.collection.children.link(col)
    mats = B.materials()

    objs, bones, chains = B.build_body(col, mats)
    frames = {}
    for side in ("L", "R"):
        fr = B.body_arm_frame(side)
        frames[side] = fr
        o, b, c = B.build_arm(fr, col, mats["red"])
        for bd in b:
            if bd["name"].startswith("Shoulder"):
                bd["parent"] = "Chest"
        objs += o
        bones += b
        chains += c

    groups = [
        ("Body", lambda n: n in ("Root", "Hips", "Spine", "Chest", "Head") or n.startswith("Eye")),
        ("Arm.L", lambda n: n.endswith(".L") and n.startswith(("Shoulder", "UpperArm", "LowerArm", "Hand"))),
        ("Arm.R", lambda n: n.endswith(".R") and n.startswith(("Shoulder", "UpperArm", "LowerArm", "Hand"))),
        ("Fingers.L", lambda n: n.endswith(".L") and n.startswith(("Index", "Middle", "Ring", "Thumb"))),
        ("Fingers.R", lambda n: n.endswith(".R") and n.startswith(("Index", "Middle", "Ring", "Thumb"))),
        ("Legs", lambda n: n.startswith(("UpperLeg", "LowerLeg", "Foot", "Toe"))),
    ]
    arm = B.build_armature("RedBean_Rig", bones, col, groups)
    mesh = B.skin_and_join("RedBean_Mesh", objs, chains, arm, col)
    return arm, mesh, frames, mats


def make_poses(arm, frames):
    L, R = frames["L"], frames["R"]
    acts = {}
    acts["TPose"] = B.make_action(arm, "TPose", {})

    rots = {}
    for fr in (L, R):
        s = fr.side
        rots[f"UpperArm.{s}"] = (-72.0, 0.0, 0.0)          # arms hang down
        rots[f"LowerArm.{s}"] = (-8.0, -fr.curl * 70.0, 0.0)  # slight elbow, palms inward
        B.curl_hand(rots, fr, fingers=(14.0, 18.0, 12.0), thumb=(10.0, 12.0), spread=4.0)
    rots["Head"] = (0.0, 0.0, 6.0)
    acts["Idle"] = B.make_action(arm, "Idle", rots)

    rots = {}
    for fr in (L, R):
        s = fr.side
        rots[f"UpperArm.{s}"] = (-40.0, 0.0, 0.0)
        rots[f"LowerArm.{s}"] = (0.0, 0.0, fr.curl * 55.0)     # bend elbows forward
        B.curl_hand(rots, fr, fingers=(78.0, 92.0, 62.0), thumb=(38.0, 48.0), thumb_sweep=28.0)
    rots["Eye.L"] = (10.0, 0.0, 0.0)
    rots["Eye.R"] = (10.0, 0.0, 0.0)
    acts["Fist"] = B.make_action(arm, "Fist", rots)

    rots = {}
    B.curl_hand(rots, L, fingers=(0.0, 0.0, 0.0), spread=12.0)
    rots["UpperArm.L"] = (12.0, 0.0, 0.0)
    rots["LowerArm.L"] = (78.0, 0.0, 0.0)               # forearm up -> waving
    rots["Hand.L"] = (0.0, 0.0, L.curl * -12.0)
    rots["UpperArm.R"] = (-72.0, 0.0, 0.0)
    rots["LowerArm.R"] = (-8.0, -R.curl * 70.0, 0.0)
    B.curl_hand(rots, R, fingers=(14.0, 18.0, 12.0), thumb=(10.0, 12.0), spread=4.0)
    rots["Hips"] = (0.0, 0.0, -8.0)
    acts["Wave"] = B.make_action(arm, "Wave", rots)
    return acts


def render_sheets(scene, arm, mesh, mats, acts, out_dir):
    rdir = os.path.join(out_dir, "renders")
    os.makedirs(rdir, exist_ok=True)
    B.setup_render(scene)
    cam = B.ortho_camera(scene, "TurnCam", 3.0)

    B.set_action(arm, acts["TPose"])
    files = B.render_views(scene, cam, B.TURN_VIEWS, rdir, "view_")
    B.compose_sheet(files, os.path.join(rdir, "turnaround.png"))

    # rig sheet: semi-transparent body with the bones drawn through it
    viz = B.bone_viz(scene, arm)
    B.set_alpha([mats["red"], mats["white"], mats["black"]], 0.30)
    files = B.render_views(scene, cam, B.TURN_VIEWS[:2], rdir, "rig_")
    B.set_alpha([mats["red"], mats["white"], mats["black"]], 1.0)
    B.remove_collection(viz)
    # close-up of one hand with its bones
    viz = B.bone_viz(scene, arm)
    B.set_alpha([mats["red"]], 0.30)
    hand_c = arm.matrix_world @ arm.pose.bones["Hand.L"].tail
    cam.data.ortho_scale = 0.75
    B.light_from(scene, (0, -10, 1.0), hand_c)
    cam.location = (hand_c.x + 0.08, -10, hand_c.z)
    cam.rotation_euler = (math.pi / 2, 0, 0)
    files.append(("hand rig", B.render(scene, os.path.join(rdir, "rig_hand.png"))))
    B.set_alpha([mats["red"]], 1.0)
    B.remove_collection(viz)
    cam.data.ortho_scale = 3.0
    B.compose_sheet(files, os.path.join(rdir, "rig.png"))

    # poses
    files = []
    for name in ("TPose", "Idle", "Fist", "Wave"):
        B.set_action(arm, acts[name])
        cam.location, cam.rotation_euler = (0, -10, 1.0), (math.pi / 2, 0, 0)
        B.light_from(scene, (0, -10, 1.0))
        files.append((name, B.render(scene, os.path.join(rdir, f"pose_{name.lower()}.png"))))
    B.compose_sheet(files, os.path.join(rdir, "poses.png"))
    B.set_action(arm, acts["TPose"])
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

    arm, mesh, frames, mats = build(scene)
    acts = make_poses(arm, frames)
    B.set_action(arm, acts["TPose"])

    B.export_all([arm, mesh], "red_bean", out_dir)
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.ops.wm.obj_export(filepath=os.path.join(out_dir, "red_bean.obj"),
                          export_selected_objects=True, apply_modifiers=True,
                          export_materials=True)

    if do_render:
        render_sheets(scene, arm, mesh, mats, acts, out_dir)

    for o in list(scene.collection.objects):
        if o.type in ("CAMERA", "LIGHT"):
            bpy.data.objects.remove(o)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "red_bean.blend"))
    print("done ->", out_dir)
    print("bones:", len(arm.data.bones), "verts:", len(mesh.data.vertices))


if __name__ == "__main__":
    main()
