# Red Bean character

Procedurally generated 3D model of the red bean mascot (front / left / back / right reference sheet).

| File | What |
|---|---|
| `generate_character.py` | Blender (bpy) script that builds, renders and exports everything |
| `red_bean.blend` | Blender scene (separate parts, parented to the `RedBean` empty, subdivision modifiers live) |
| `red_bean.glb` | glTF binary with PBR materials, modifiers applied (Unity / Unreal / Godot / three.js) |
| `red_bean.fbx` | FBX export |
| `red_bean.obj` + `.mtl` | Wavefront OBJ |
| `renders/turnaround.png` | Cycles render of the model in the same 4-view layout as the reference |

Character is 2.0 m tall, Z-up, faces -Y, T-pose. Regenerate with:

```
pip install bpy pillow
python3 character/generate_character.py character
```

Add `--no-render` to skip the Cycles turnaround.
