"""
Shared builders for the red "bean" mascot: mesh primitives, the open hand
(palm + 3 fingers + thumb), the armature, skin weights, poses, exports and
the Cycles preview renders.

Coordinate conventions (Blender): Z up, character faces -Y, +X is the
character's own left side. Units are metres; the character is 2.0 m tall.

Every arm/hand is built once in a *canonical* frame and then placed with an
`ArmFrame`:
    canonical +x : along the arm, shoulder -> finger tips  (A)
    canonical -y : palm side                               (P)
    canonical +z : thumb side                              (T)
The full body uses A=+X / P=-Y / T=+Z (T-pose, palms forward, thumbs up);
the first-person rig uses A=forward / P=down / T=inward. The right side is a
mirror of the left, so bone-local rotation signs are handled by
`ArmFrame.curl` (see the pose helpers at the bottom).
"""
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

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
SHOULDER_X = 0.30                # shoulder joint sits inside the body

LEG_X = 0.22
LEG_R = 0.105
FOOT_RADII = (0.15, 0.21, 0.115)    # plump slipper: half width, half length, half height

RED = (0.85, 0.015, 0.012, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK = (0.01, 0.01, 0.01, 1.0)

# --------------------------------------------------------------------------
# arm / hand in the canonical frame (origin = shoulder joint)
# --------------------------------------------------------------------------
ARM = dict(
    tube_start=-0.06, elbow=0.21, wrist=0.42, knuckle=0.53, hand_tail=0.53,
    r_shoulder=0.066, r_wrist=0.052,
    palm_center=(0.488, -0.004, 0.0), palm_radii=(0.094, 0.052, 0.092),
)
# name, base point, angle in the x/z plane (deg), segment lengths, r_base, r_tip
FINGERS = [
    ("Index",  (0.530, -0.004,  0.046),  21.0, (0.070, 0.065, 0.065), 0.031, 0.024),
    ("Middle", (0.535, -0.004,  0.000),   0.0, (0.072, 0.067, 0.066), 0.032, 0.025),
    ("Ring",   (0.530, -0.004, -0.046), -21.0, (0.068, 0.064, 0.063), 0.031, 0.024),
    ("Thumb",  (0.452, -0.012,  0.046),  68.0, (0.052, 0.050, 0.045), 0.033, 0.026),
]
BLEND_FINGER = 0.012
BLEND_ARM = 0.040
BLEND_BODY = 0.100
BLEND_LEG = 0.040


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def make_material(name, color, roughness=0.35, specular=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    mat.diffuse_color = color
    return mat


def materials():
    return dict(
        red=make_material("RedBean_Body", RED, roughness=0.30),
        white=make_material("RedBean_EyeWhite", WHITE, roughness=0.12),
        black=make_material("RedBean_Black", BLACK, roughness=0.25),
    )


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def mesh_object(name, verts, faces, col, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def adopt(ob, name, mat, col):
    """Take an operator-created object: rename, material, smooth, move to col."""
    ob.name = name
    ob.data.name = name
    ob.data.materials.append(mat)
    for p in ob.data.polygons:
        p.use_smooth = True
    for c in ob.users_collection:
        c.objects.unlink(ob)
    col.objects.link(ob)
    return ob


def ortho_basis(axis):
    a = Vector(axis).normalized()
    helper = Vector((0, 0, 1)) if abs(a.z) < 0.9 else Vector((1, 0, 0))
    u = a.cross(helper).normalized()
    v = a.cross(u).normalized()
    return a, u, v


def lathe(name, p0, p1, radius_fn, col, mat, segments=16, rings=32):
    """Closed surface of revolution from p0 to p1. radius_fn(t) with t in
    [0, 1] gives the radius (0 at both ends -> poles)."""
    p0, p1 = Vector(p0), Vector(p1)
    a_dir, u, v = ortho_basis(p1 - p0)
    L = (p1 - p0).length
    verts = [p0]
    for i in range(1, rings):
        th = math.pi * i / rings
        t = (1.0 - math.cos(th)) / 2.0           # dense near the ends
        r = radius_fn(t)
        c = p0 + a_dir * (t * L)
        for j in range(segments):
            ph = 2.0 * math.pi * j / segments
            verts.append(c + (u * math.cos(ph) + v * math.sin(ph)) * r)
    verts.append(p1)
    last = len(verts) - 1
    faces = []
    ring = lambda i, j: 1 + (i - 1) * segments + (j % segments)
    for j in range(segments):
        faces.append((0, ring(1, j), ring(1, j + 1)))
    for i in range(1, rings - 1):
        for j in range(segments):
            faces.append((ring(i, j), ring(i + 1, j), ring(i + 1, j + 1), ring(i, j + 1)))
    for j in range(segments):
        faces.append((ring(rings - 1, j), last, ring(rings - 1, j + 1)))
    return mesh_object(name, verts, faces, col, mat)


def capsule(name, p0, p1, r0, r1, col, mat, segments=16, rings=36):
    """Tapered capsule: hemisphere of radius r0 at p0, r1 at p1, straight
    tapered tube in between. Evenly ringed so it bends nicely when skinned."""
    p0, p1 = Vector(p0), Vector(p1)
    L = (p1 - p0).length
    total = L + r0 + r1

    def rad(t):
        a = -r0 + t * total
        if a < 0:
            return r0 * math.sqrt(max(0.0, 1.0 - (a / r0) ** 2))
        if a > L:
            return r1 * math.sqrt(max(0.0, 1.0 - ((a - L) / r1) ** 2))
        return r0 + (r1 - r0) * a / L

    a_dir = (p1 - p0).normalized()
    return lathe(name, p0 - a_dir * r0, p1 + a_dir * r1, rad, col, mat, segments, rings)


def ellipsoid(name, center, radii, col, mat, segments=32, rings=24, shape=None):
    """Ellipsoid; optional shape(x, y, z) -> (x, y, z) on the unit sphere."""
    c = Vector(center)
    rx, ry, rz = radii
    verts = []
    for i in range(rings + 1):
        th = math.pi * i / rings
        for j in range(segments):
            ph = 2.0 * math.pi * j / segments
            x, y, z = math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)
            if shape:
                x, y, z = shape(x, y, z)
            verts.append(c + Vector((x * rx, y * ry, z * rz)))
    faces = []
    for i in range(rings):
        for j in range(segments):
            a = i * segments + j
            b = i * segments + (j + 1) % segments
            cc = (i + 1) * segments + (j + 1) % segments
            d = (i + 1) * segments + j
            if i == 0:
                faces.append((a, d, cc))
            elif i == rings - 1:
                faces.append((a, d, b))
            else:
                faces.append((a, d, cc, b))
    return mesh_object(name, verts, faces, col, mat)


# --------------------------------------------------------------------------
# arm frame: places the canonical arm / hand in the world
# --------------------------------------------------------------------------
class ArmFrame:
    def __init__(self, side, origin, A, P):
        self.side = side
        self.origin = Vector(origin)
        self.A = Vector(A).normalized()
        P = Vector(P)
        self.P = (P - P.project(self.A)).normalized()
        # left is a proper rotation of the canonical frame, right is a mirror
        self.T = self.P.cross(self.A) if side == "L" else self.A.cross(self.P)
        self.M = Matrix((self.A, -self.P, self.T)).transposed()   # columns
        self.mirror = self.M.determinant() < 0
        # bone-local rotation sign that curls a finger toward the palm
        self.curl = -1.0 if side == "L" else 1.0

    def world(self, v):
        return self.origin + self.M @ Vector(v)

    def dir(self, v):
        return (self.M @ Vector(v)).normalized()

    def matrix4(self):
        m = self.M.to_4x4()
        m.translation = self.origin
        return m


def sfx(name, side):
    return f"{name}.{side}"


def finger_points(fdef):
    """Joint points of one finger in the canonical frame."""
    name, base, ang, lens, r0, r1 = fdef
    d = Vector((math.cos(math.radians(ang)), 0.0, math.sin(math.radians(ang))))
    pts = [Vector(base)]
    for L in lens:
        pts.append(pts[-1] + d * L)
    return pts


def build_arm(frame, col, mat, tube_start=None):
    """Arm tube + palm + fingers for one side. Returns (objects, bones,
    chains) where bones are world-space bone specs and chains are the
    weight chains to skin each object with."""
    s = frame.side
    W = frame.world
    ts = ARM["tube_start"] if tube_start is None else tube_start
    objs, bones, chains = [], [], []

    tube = capsule(sfx("ArmTube", s), (ts, 0, 0), (ARM["wrist"] + 0.02, 0, 0),
                   ARM["r_shoulder"], ARM["r_wrist"], col, mat, segments=24, rings=48)
    palm = ellipsoid(sfx("Palm", s), ARM["palm_center"], ARM["palm_radii"], col, mat)
    objs += [tube, palm]

    shoulder_head = (ts - 0.12, 0.0, 0.04)
    arm_chain = [
        (sfx("Shoulder", s), W(shoulder_head), W((0, 0, 0))),
        (sfx("UpperArm", s), W((0, 0, 0)), W((ARM["elbow"], 0, 0))),
        (sfx("LowerArm", s), W((ARM["elbow"], 0, 0)), W((ARM["wrist"], 0, 0))),
        (sfx("Hand", s), W((ARM["wrist"], 0, 0)), W((ARM["hand_tail"], 0, 0))),
    ]
    chains.append((tube, arm_chain, BLEND_ARM))
    chains.append((palm, arm_chain[2:], BLEND_ARM * 0.6))

    T_roll = frame.T
    bones += [
        dict(name=sfx("Shoulder", s), head=W(shoulder_head), tail=W((0, 0, 0)), roll=T_roll),
        dict(name=sfx("UpperArm", s), head=W((0, 0, 0)), tail=W((ARM["elbow"], 0, 0)),
             parent=sfx("Shoulder", s), roll=T_roll),
        dict(name=sfx("LowerArm", s), head=W((ARM["elbow"], 0, 0)), tail=W((ARM["wrist"], 0, 0)),
             parent=sfx("UpperArm", s), roll=T_roll, connect=True),
        dict(name=sfx("Hand", s), head=W((ARM["wrist"], 0, 0)), tail=W((ARM["hand_tail"], 0, 0)),
             parent=sfx("LowerArm", s), roll=T_roll, connect=True),
    ]

    for fdef in FINGERS:
        fname, base, ang, lens, r0, r1 = fdef
        pts = finger_points(fdef)
        ob = capsule(sfx(fname, s), pts[0], pts[-1], r0, r1, col, mat, segments=16, rings=40)
        objs.append(ob)
        roll = -frame.A if fname == "Thumb" else T_roll
        chain = [(sfx("Hand", s), W((ARM["wrist"], 0, 0)), W(pts[0]))]
        parent = sfx("Hand", s)
        for k in range(len(lens)):
            bname = f"{fname}.{k + 1:02d}.{s}"
            bones.append(dict(name=bname, head=W(pts[k]), tail=W(pts[k + 1]), parent=parent,
                              roll=roll, connect=k > 0))
            chain.append((bname, W(pts[k]), W(pts[k + 1])))
            parent = bname
        chains.append((ob, chain, BLEND_FINGER))

    if frame.mirror:
        for ob in objs:
            ob.data.transform(frame.matrix4())
    else:
        for ob in objs:
            ob.data.transform(frame.matrix4())
    for ob in objs:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(ob.data)
        bm.free()
        ob.data.update()
    return objs, bones, chains


# --------------------------------------------------------------------------
# body, face, legs
# --------------------------------------------------------------------------
def body_profile(t):
    taper = 1.0 - TAPER * t
    bulge = 1.0 + 0.06 * math.exp(-((t - 0.35) / 0.25) ** 2)
    return taper * bulge


def build_body(col, mats):
    """Body, eyes, pupils, mouth, legs, feet. Returns (objects, bones, chains)."""
    objs, bones, chains = [], [], []
    half_len = (BODY_HEIGHT - 2 * CAP_R) / 2.0

    def shape(x, y, z):
        return x, y, z

    body = ellipsoid("Body", (0, 0, 0), (1, 1, 1), col, mats["red"], segments=64, rings=48)
    for v in body.data.vertices:
        x, y, z = v.co
        zc = z * CAP_R + math.copysign(half_len, z)
        t = (zc + BODY_HEIGHT / 2.0) / BODY_HEIGHT
        sc = body_profile(t)
        X = x * BODY_RX * sc
        Y = y * BODY_RY * sc
        if Y < 0:
            Y *= 1.0 + 0.14 * (1.0 - t) ** 1.6
        v.co = (X, Y, zc + BODY_HEIGHT / 2.0 + BODY_BOTTOM_Z)
    body.data.update()
    objs.append(body)

    spine = [
        ("Root", (0, 0, 0), (0, 0.25, 0)),
        ("Hips", (0, 0, 0.45), (0, 0, 0.62)),
        ("Spine", (0, 0, 0.62), (0, 0, 0.95)),
        ("Chest", (0, 0, 0.95), (0, 0, 1.30)),
        ("Head", (0, 0, 1.30), (0, 0, 2.0)),
    ]
    bones.append(dict(name="Root", head=(0, 0, 0), tail=(0, 0.25, 0)))
    parent = "Root"
    for n, h, t in spine[1:]:
        bones.append(dict(name=n, head=h, tail=t, parent=parent, connect=parent != "Root"))
        parent = n
    body_chain = [(n, Vector(h), Vector(t)) for n, h, t in spine[1:]]
    chains.append((body, body_chain, BLEND_BODY))

    def surface_y(x, z):
        ok, loc, _n, _i = body.ray_cast(Vector((x, -5.0, z)), Vector((0, 1, 0)))
        return loc.y if ok else -BODY_RY

    # eyes: the character's right eye (viewer's left, -X) a hair larger and lower
    eyes = [("R", -EYE_X, EYE_R * 1.03, EYE_Z - 0.012),
            ("L", +EYE_X, EYE_R * 0.98, EYE_Z + 0.006)]
    for side, ex, er, ez in eyes:
        ys = surface_y(ex, ez)
        ey = ys - er * 0.30
        eye = ellipsoid(sfx("Eye", side), (ex, ey, ez), (er, er, er), col, mats["white"],
                        segments=48, rings=24)
        look = Vector((0.18, -1.0, -0.22)).normalized()
        pc = Vector((ex, ey, ez)) + look * (er * 0.93)
        pupil = ellipsoid(sfx("Pupil", side), (0, 0, 0), (PUPIL_R, PUPIL_R * 0.35, PUPIL_R),
                          col, mats["black"], segments=32, rings=16)
        m = look.to_track_quat("-Y", "Z").to_matrix().to_4x4()
        m.translation = pc
        pupil.data.transform(m)
        pupil.data.update()
        bname = sfx("Eye", side)
        bones.append(dict(name=bname, head=(ex, ey, ez), tail=(ex, ey - er, ez), parent="Head",
                          roll=Vector((0, 0, 1))))
        for ob in (eye, pupil):
            objs.append(ob)
            chains.append((ob, [(bname, Vector((ex, ey, ez)), Vector((ex, ey - er, ez)))], 0.01))

    # mouth: small flat, slightly sad line
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
        z = MOUTH_Z + 0.012 - 0.024 * u * u
        y = surface_y(x, z) - 0.001
        bp.co = (x, y, z)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    mouth = bpy.data.objects.new("Mouth", curve)
    col.objects.link(mouth)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = mouth
    mouth.select_set(True)
    bpy.ops.object.convert(target="MESH")
    mouth = adopt(bpy.context.active_object, "Mouth", mats["black"], col)
    objs.append(mouth)
    chains.append((mouth, [("Head", Vector((0, 0, 1.30)), Vector((0, 0, 2.0)))], 0.01))

    # legs + feet
    for side, sgn in (("L", 1.0), ("R", -1.0)):
        lx = sgn * LEG_X
        curve = bpy.data.curves.new(sfx("Leg", side), "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = LEG_R
        curve.bevel_resolution = 10
        curve.resolution_u = 24
        curve.use_fill_caps = True
        spline = curve.splines.new("BEZIER")
        pts = [(lx, 0.03, 0.60, 1.00), (lx, 0.03, 0.42, 1.00),
               (lx, 0.01, 0.22, 0.85), (lx, -0.05, 0.09, 0.90)]
        spline.bezier_points.add(len(pts) - 1)
        for bp, (x, y, z, r) in zip(spline.bezier_points, pts):
            bp.co = (x, y, z)
            bp.radius = r
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        leg = bpy.data.objects.new(sfx("Leg", side), curve)
        col.objects.link(leg)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = leg
        leg.select_set(True)
        bpy.ops.object.convert(target="MESH")
        leg = adopt(bpy.context.active_object, sfx("Leg", side), mats["red"], col)

        rx, ry, rz = FOOT_RADII

        def foot_shape(x, y, z):
            if y < 0:
                yy = y
                z = z * (1.0 - 0.22 * (-y))
            else:
                yy = y * 0.55
            return x, yy, max(z, -0.02 / rz)

        foot = ellipsoid(sfx("Foot", side), (lx, -0.11, 0.095), FOOT_RADII, col, mats["red"],
                         segments=48, rings=24, shape=foot_shape)
        objs += [leg, foot]

        hip, knee = Vector((lx, 0.03, 0.62)), Vector((lx, 0.02, 0.32))
        ankle, ball, toe = Vector((lx, -0.02, 0.14)), Vector((lx, -0.20, 0.05)), Vector((lx, -0.32, 0.03))
        bones += [
            dict(name=sfx("UpperLeg", side), head=hip, tail=knee, parent="Hips"),
            dict(name=sfx("LowerLeg", side), head=knee, tail=ankle, parent=sfx("UpperLeg", side), connect=True),
            dict(name=sfx("Foot", side), head=ankle, tail=ball, parent=sfx("LowerLeg", side), connect=True),
            dict(name=sfx("Toe", side), head=ball, tail=toe, parent=sfx("Foot", side), connect=True),
        ]
        leg_chain = [(sfx("UpperLeg", side), hip, knee), (sfx("LowerLeg", side), knee, ankle),
                     (sfx("Foot", side), ankle, ball)]
        chains.append((leg, leg_chain, BLEND_LEG))
        chains.append((foot, [(sfx("LowerLeg", side), knee, ankle), (sfx("Foot", side), ankle, ball),
                              (sfx("Toe", side), ball, toe)], BLEND_LEG * 0.75))
    return objs, bones, chains


def body_arm_frame(side):
    sgn = 1.0 if side == "L" else -1.0
    return ArmFrame(side, (sgn * SHOULDER_X, 0.0, ARM_Z), (sgn, 0, 0), (0, -1, 0))


# --------------------------------------------------------------------------
# armature + skinning
# --------------------------------------------------------------------------
def build_armature(name, bones, col, groups=None):
    arm_data = bpy.data.armatures.new(name)
    arm_data.display_type = "OCTAHEDRAL"
    arm = bpy.data.objects.new(name, arm_data)
    arm.show_in_front = True
    col.objects.link(arm)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for b in bones:
        eb = arm_data.edit_bones.new(b["name"])
        eb.head = Vector(b["head"])
        eb.tail = Vector(b["tail"])
        if b.get("roll") is not None:
            eb.align_roll(Vector(b["roll"]))
    for b in bones:
        if b.get("parent"):
            eb = arm_data.edit_bones[b["name"]]
            eb.parent = arm_data.edit_bones[b["parent"]]
            eb.use_connect = bool(b.get("connect"))
    bpy.ops.object.mode_set(mode="OBJECT")
    if groups:
        for gname, pred in groups:
            bc = arm_data.collections.new(gname)
            for bone in arm_data.bones:
                if pred(bone.name):
                    bc.assign(bone)
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    return arm


def chain_weights(ob, chain, blend):
    """Assign vertex-group weights along a polyline of bones.
    chain = [(bone_name, head, tail), ...] in world space, consecutive."""
    segs = [(n, Vector(p0), Vector(p1)) for n, p0, p1 in chain]
    lens = [(p1 - p0).length for _, p0, p1 in segs]
    cum = [0.0]
    for L in lens:
        cum.append(cum[-1] + L)
    groups = {}
    for n, _, _ in segs:
        groups[n] = ob.vertex_groups.get(n) or ob.vertex_groups.new(name=n)
    mw = ob.matrix_world
    n_seg = len(segs)
    for v in ob.data.vertices:
        p = mw @ v.co
        best = None
        for i, (n, p0, p1) in enumerate(segs):
            d = p1 - p0
            t = min(1.0, max(0.0, (p - p0).dot(d) / d.length_squared))
            dist = (p - (p0 + d * t)).length
            if best is None or dist < best[0]:
                best = (dist, cum[i] + t * lens[i])
        s = best[1]
        g = [1.0] + [smoothstep((s - (cum[k] - blend)) / (2.0 * blend)) for k in range(1, n_seg)] + [0.0]
        for i, (n, _, _) in enumerate(segs):
            w = g[i] - g[i + 1]
            if w > 1e-4:
                groups[n].add([v.index], w, "REPLACE")


def skin_and_join(name, objs, chains, arm, col):
    for ob, chain, blend in chains:
        chain_weights(ob, chain, blend)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    mesh = bpy.context.active_object
    mesh.name = name
    mesh.data.name = name
    mod = mesh.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mesh.parent = arm
    return mesh


# --------------------------------------------------------------------------
# poses
# --------------------------------------------------------------------------
def finger_bones(side, names=("Index", "Middle", "Ring")):
    return [f"{n}.{k:02d}.{side}" for n in names for k in (1, 2, 3)]


def curl_hand(rots, frame, fingers=(0.0, 0.0, 0.0), thumb=(0.0, 0.0), thumb_sweep=0.0,
              spread=0.0, names=("Index", "Middle", "Ring")):
    """Bone-local rotations (degrees) that curl the fingers of one hand.
    fingers: curl per joint; thumb: curl of the 2 distal thumb joints;
    thumb_sweep: swing the whole thumb toward the finger tips; spread: fan."""
    s = frame.side
    c = frame.curl
    spread_by = {"Index": +spread, "Middle": 0.0, "Ring": -spread}
    for n in names:
        for k, a in enumerate(fingers, start=1):
            rots[f"{n}.{k:02d}.{s}"] = (spread_by[n] if k == 1 else 0.0, 0.0, c * a)
    rots[f"Thumb.01.{s}"] = (-thumb_sweep, 0.0, c * thumb[0] * 0.5)
    rots[f"Thumb.02.{s}"] = (0.0, 0.0, c * thumb[0])
    rots[f"Thumb.03.{s}"] = (0.0, 0.0, c * thumb[1])
    return rots


def apply_pose(arm, rots):
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
    for name, (x, y, z) in rots.items():
        arm.pose.bones[name].rotation_euler = (math.radians(x), math.radians(y), math.radians(z))
    bpy.context.view_layer.update()


def make_action(arm, name, rots, frames=(1, 24)):
    """Store a pose as an action (keyed on every bone so actions are
    self-contained). Returns the action; leaves it assigned."""
    if arm.animation_data is None:
        arm.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act      # assign first: an old action would overwrite the pose on update
    apply_pose(arm, rots)
    for f in frames:
        for pb in arm.pose.bones:
            pb.keyframe_insert("rotation_euler", frame=f, group=pb.name)
    act.frame_range = (frames[0], frames[-1])
    return act


def set_action(arm, act):
    arm.animation_data.action = act
    bpy.context.scene.frame_set(int(act.frame_range[0]))
    bpy.context.view_layer.update()


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------
def export_all(objs, stem, out_dir):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, stem + ".glb"),
                              export_format="GLB", use_selection=True, export_apply=True,
                              export_skins=True, export_animations=True,
                              export_animation_mode="ACTIONS", export_yup=True)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out_dir, stem + ".fbx"),
                             use_selection=True, use_mesh_modifiers=True,
                             add_leaf_bones=False, bake_anim=True,
                             bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False,
                             bake_anim_simplify_factor=0.0)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def setup_render(scene, samples=48, size=(600, 800)):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    world = bpy.data.worlds.get("Grey") or bpy.data.worlds.new("Grey")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.42, 0.42, 0.42, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world


def clear_lights(scene):
    for o in [o for o in scene.collection.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(o)


def add_light(scene, name, kind, loc, energy, size=2.0, target=(0, 0, 1.0)):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    if kind == "AREA":
        ld.size = size
    lo = bpy.data.objects.new(name, ld)
    lo.location = loc
    lo.rotation_euler = (Vector(loc) - Vector(target)).to_track_quat("Z", "Y").to_euler()
    scene.collection.objects.link(lo)
    return lo


def light_from(scene, view_dir, target=(0, 0, 1.0), key=450, fill=160):
    clear_lights(scene)
    v = Vector(view_dir).normalized()
    right = v.cross(Vector((0, 0, 1))).normalized()
    t = Vector(target)
    add_light(scene, "Key", "AREA", tuple(t + v * 5 + right * -3 + Vector((0, 0, 3))), key, 3, target)
    add_light(scene, "Fill", "AREA", tuple(t + v * 5 + right * 3 + Vector((0, 0, 0))), fill, 4, target)


def render(scene, path):
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def ortho_camera(scene, name="TurnCam", scale=3.0):
    cam_d = bpy.data.cameras.new(name)
    cam_d.type = "ORTHO"
    cam_d.ortho_scale = scale
    cam = bpy.data.objects.new(name, cam_d)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


TURN_VIEWS = [("front", (0, -10, 1.0), (math.pi / 2, 0, 0)),
              ("left", (10, 0, 1.0), (math.pi / 2, 0, math.pi / 2)),
              ("back", (0, 10, 1.0), (math.pi / 2, 0, math.pi)),
              ("right", (-10, 0, 1.0), (math.pi / 2, 0, -math.pi / 2))]


def render_views(scene, cam, views, out_dir, prefix, target=(0, 0, 1.0)):
    files = []
    for name, loc, rot in views:
        light_from(scene, loc, target)
        cam.location = loc
        cam.rotation_euler = rot
        files.append((name, render(scene, os.path.join(out_dir, f"{prefix}{name}.png"))))
    return files


def compose_sheet(files, out_path, label_h=70, bg=(107, 107, 107)):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    imgs = [Image.open(p).convert("RGB") for _, p in files]
    w, h = imgs[0].size
    sheet = Image.new("RGB", (w * len(imgs), h + label_h), bg)
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    for i, ((name, _), im) in enumerate(zip(files, imgs)):
        sheet.paste(im, (i * w, 0))
        txt = name.upper().replace("_", " ")
        tw = draw.textlength(txt, font=font)
        draw.text((i * w + (w - tw) / 2, h + 12), txt, fill=(20, 20, 20), font=font)
    sheet.save(out_path)
    return out_path


# ---- bone visualisation (Cycles cannot draw bones) --------------------------
BONE_COLORS = [
    (lambda n: n.startswith(("Index", "Middle", "Ring", "Thumb")), (0.1, 0.95, 0.2, 1)),
    (lambda n: n.startswith(("Shoulder", "UpperArm", "LowerArm", "Hand")), (0.1, 0.8, 1.0, 1)),
    (lambda n: n.startswith(("UpperLeg", "LowerLeg", "Foot", "Toe")), (1.0, 0.2, 0.9, 1)),
    (lambda n: n.startswith("Eye"), (1.0, 1.0, 1.0, 1)),
    (lambda n: True, (1.0, 0.9, 0.1, 1)),
]


def bone_viz(scene, arm, col_name="RigViz"):
    """Emissive sticks + joint balls along every bone (posed). Returns the
    collection so the caller can remove it after rendering."""
    col = bpy.data.collections.new(col_name)
    scene.collection.children.link(col)
    mats = {}
    for i, (_, color) in enumerate(BONE_COLORS):
        m = bpy.data.materials.new(f"BoneViz{i}")
        m.use_nodes = True
        bsdf = m.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 1.5
        mats[i] = m
    mw = arm.matrix_world
    for pb in arm.pose.bones:
        h, t = mw @ pb.head, mw @ pb.tail
        idx = next(i for i, (pred, _) in enumerate(BONE_COLORS) if pred(pb.name))
        L = (t - h).length
        r = min(0.018, max(0.006, L * 0.12))
        lathe(f"viz_{pb.name}", h, t, lambda u, r=r: r * math.sqrt(max(0.0, 1 - (2 * u - 1) ** 2)) * (1.2 - 0.6 * u),
              col, mats[idx], segments=10, rings=8)
        ellipsoid(f"vizj_{pb.name}", h, (r * 1.4,) * 3, col, mats[idx], segments=12, rings=8)
    return col


def remove_collection(col):
    for ob in list(col.objects):
        me = ob.data
        bpy.data.objects.remove(ob)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)


def set_alpha(mats, alpha):
    for m in mats:
        m.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
