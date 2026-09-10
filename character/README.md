# Red Bean character (rigged) + first-person hands

Procedurally generated, fully rigged 3D model of the red bean mascot
(full-body reference sheet + first-person hand poses A/B/C).

![turnaround](renders/turnaround.png)
![rig](renders/rig.png)
![poses](renders/poses.png)
![first person](renders/fp_sheet.png)

## Files

| File | What |
|---|---|
| `beanlib.py` | shared builders: primitives, open hand, armature, skin weights, poses, export, renders |
| `generate_character.py` | builds the full body, rigs it, exports and renders |
| `generate_fp_hands.py` | builds the first-person arms/hands viewmodel, rig, 3 poses, props |
| `red_bean.blend` | full body: `RedBean_Mesh` (one skinned mesh, 3 materials) + `RedBean_Rig` armature, actions `TPose` `Idle` `Fist` `Wave` |
| `red_bean.glb` | glTF binary with skin + the 4 actions as animations (Unity / Unreal / Godot / three.js) |
| `red_bean.fbx` | FBX with armature + baked actions |
| `red_bean.obj` + `.mtl` | static T-pose mesh (no rig) |
| `fp_hands.blend` | first-person: `FPHands_Mesh` + `FPHands_Rig`, `FP_Camera` (parented to the `Root` bone), actions `FP_Idle` `FP_HoldItem` `FP_PullDrag`, hidden props `Prop_Box` / `Prop_Bar` |
| `fp_hands.glb` / `fp_hands.fbx` | first-person hands with skin + the 3 actions |
| `renders/turnaround.png` | front / left / back / right, T-pose |
| `renders/rig.png` | bones drawn through a transparent body + hand close-up |
| `renders/poses.png` | TPose / Idle / Fist / Wave |
| `renders/fp_sheet.png` | first-person A. idle, B. hold item, C. pull / drag (from `FP_Camera`) |

Character is 2.0 m tall, Z-up, faces -Y (+X = the character's own left),
rest pose = T-pose with open hands, palms forward, thumbs up.

## Rig

47 bones (full body), 33 bones (first-person). `.L` / `.R` suffixes work
with Blender's X-mirror pose tools. Bone collections: Body, Arm.L/R,
Fingers.L/R, Legs.

```
Root
└─ Hips ─ Spine ─ Chest ─ Head ─ Eye.L / Eye.R        (rotate Eye.* to move the pupils)
   │              └─ Shoulder.X ─ UpperArm.X ─ LowerArm.X ─ Hand.X
   │                                                     ├─ Index.01 ─ Index.02 ─ Index.03
   │                                                     ├─ Middle.01 ─ Middle.02 ─ Middle.03
   │                                                     ├─ Ring.01 ─ Ring.02 ─ Ring.03
   │                                                     └─ Thumb.01 ─ Thumb.02 ─ Thumb.03
   └─ UpperLeg.X ─ LowerLeg.X ─ Foot.X ─ Toe.X
```

First-person rig: `Root` (at the camera) → `Shoulder.X` → same arm/finger
chain as above. Moving `Root` moves camera and arms together.

Bone-local axes are set up so poses are easy to author by hand:

* every arm / finger bone: local **Y** along the bone, local **Z** toward the
  thumb side, local **X** = palm normal (left) / back of hand (right);
* **curl** a finger: rotate about local Z (negative on `.L`, positive on `.R`,
  see `ArmFrame.curl`);
* **spread** a finger: rotate about local X (positive = toward the thumb);
* **pronate** the forearm: rotate `LowerArm.X` about local Y.

`beanlib.curl_hand()` builds a whole hand pose from a few angles; see the
`make_poses()` functions for the shipped poses.

Weights are computed analytically (`beanlib.chain_weights`): each vertex is
projected onto its bone chain and blended with a smoothstep around every
joint, so fingers, elbows, knees and the spine bend cleanly without heat
weighting.

## Regenerate

```
pip install bpy pillow            # Blender 4.2 as a Python module
python3 character/generate_character.py character
python3 character/generate_fp_hands.py character
```

Add `--no-render` to skip the Cycles renders. The scripts also run inside
Blender: `blender -b -P character/generate_character.py -- character`.
