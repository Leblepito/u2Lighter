"""Procedural disposable lighter (Blender bmesh), built in millimetres.

Local frame: origin = centre of the flat bottom, +Z up, +X = spark-wheel end
(toward the figure), -X = gas-button end (away from the figure).
Dimensions: oval body 24 x 12 mm, gas-button top at 50 mm, wheel top at 60 mm.
"""
import math

import bmesh
import bpy
import numpy as np

A, B = 12.0, 6.0          # body semi-axes (24 x 12 mm)
BODY_TOP = 44.6           # top of black body under hood / button
HOOD_Z0, HOOD_Z1 = 42.5, 56.0
HOOD_X0 = -0.6            # hood covers x > HOOD_X0
BUTTON_X1 = -1.4          # button covers x < BUTTON_X1
BUTTON_TOP = 50.0
WHEEL_R, WHEEL_X = 4.5, 5.0
WHEEL_Z = 60.0 - WHEEL_R  # wheel top at exactly 60 mm
N = 128                   # segments of the full oval


def _ellipse(a, b, n=N):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.stack([a * np.cos(t), b * np.sin(t)], 1)


def _d_outline(a, b, x0, side, n=64):
    """Closed outline: part of ellipse (a,b) with side*x > side*x0, closed by a
    straight chord at x = x0. side=+1 -> wheel end, -1 -> button end."""
    tc = math.acos(max(-1.0, min(1.0, x0 / a)))  # angle where x = x0
    if side > 0:
        t = np.linspace(-tc, tc, n)
    else:
        t = np.linspace(tc, 2 * math.pi - tc, n)
    arc = np.stack([a * np.cos(t), b * np.sin(t)], 1)
    y0, y1 = arc[-1, 1], arc[0, 1]
    m = 12  # fixed so that outlines with different insets can be lofted
    chord = np.stack([np.full(m - 1, x0), np.linspace(y0, y1, m + 1)[1:-1]], 1)
    return np.concatenate([arc, chord])


def _loft(bm, rings, cap_bottom=True, cap_top=True, smooth=True):
    """rings: list of (outline (n,2), z). Same n for all rings."""
    vs = []
    for ol, z in rings:
        vs.append([bm.verts.new((float(x), float(y), float(z))) for x, y in ol])
    faces = []
    for r0, r1 in zip(vs[:-1], vs[1:]):
        n = len(r0)
        for i in range(n):
            f = bm.faces.new((r0[i], r0[(i + 1) % n], r1[(i + 1) % n], r1[i]))
            f.smooth = smooth
            faces.append(f)
    if cap_bottom:
        bm.faces.new(list(reversed(vs[0])))
    if cap_top:
        bm.faces.new(vs[-1])
    return vs


def _fillet_rings(make, z0, z1, rb, rt, steps=6):
    """Rings for a vertical prism with rounded bottom (radius rb) / top (rt).
    make(d) -> outline inset by d."""
    rings = []
    for k in range(steps + 1):
        a = k / steps * math.pi / 2
        rings.append((make(rb - rb * math.sin(a)), z0 + rb - rb * math.cos(a)))
    for k in range(steps + 1):
        a = k / steps * math.pi / 2
        rings.append((make(rt - rt * math.cos(a)), z1 - rt + rt * math.sin(a)))
    return rings


def _mesh_obj(name, bm, mat, coll):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def _cylinder_y(bm, r, y0, y1, cx, cz, n=48, profile=None):
    """Cylinder along Y. profile: optional radii list (len n) for knurling."""
    rad = profile if profile is not None else [r] * n
    rings = []
    for y in (y0, y1):
        ring = []
        for i in range(n):
            t = 2 * math.pi * i / n
            ring.append(bm.verts.new((cx + rad[i] * math.cos(t), y, cz + rad[i] * math.sin(t))))
        rings.append(ring)
    for i in range(n):
        bm.faces.new((rings[0][i], rings[0][(i + 1) % n], rings[1][(i + 1) % n], rings[1][i]))
    bm.faces.new(rings[0])
    bm.faces.new(list(reversed(rings[1])))


def _box(bm, x0, x1, y0, y1, z0, z1):
    v = [bm.verts.new((x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    idx = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    for f in idx:
        bm.faces.new([v[i] for i in f])


def make_materials():
    def pr(name, color, rough, metal=0.0, spec=0.5, coat=0.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (*color, 1.0)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        b.inputs["Specular IOR Level"].default_value = spec
        if coat:
            b.inputs["Coat Weight"].default_value = coat
            b.inputs["Coat Roughness"].default_value = 0.08
        return m
    return {
        "body": pr("Lighter_Body_BlackPlastic", (0.012, 0.012, 0.013), 0.32, spec=0.5, coat=0.25),
        "button": pr("Lighter_Button_BlackPlastic", (0.015, 0.015, 0.016), 0.55, spec=0.45),
        "chrome": pr("Lighter_Hood_Chrome", (0.86, 0.86, 0.88), 0.12, metal=1.0),
        "steel": pr("Lighter_Wheel_Steel", (0.62, 0.62, 0.64), 0.32, metal=1.0),
        "brass": pr("Lighter_Nozzle_Metal", (0.55, 0.55, 0.56), 0.3, metal=1.0),
    }


def build_lighter(coll, parent=None):
    """Create lighter parts (mm, local frame). Returns list of objects."""
    mats = make_materials()
    objs = []

    # body: full oval up to HOOD_Z0, then a 0.45 mm narrower neck under the hood
    bm = bmesh.new()
    rings = _fillet_rings(lambda d: _ellipse(A - d, B - d), 0.0, HOOD_Z0 + 0.4, 0.9, 0.3)
    neck = [(_ellipse(A - 0.45, B - 0.45), HOOD_Z0 + 0.4), (_ellipse(A - 0.45, B - 0.45), BODY_TOP - 0.4),
            (_ellipse(A - 0.85, B - 0.85), BODY_TOP)]
    _loft(bm, rings + neck)
    objs.append(_mesh_obj("Lighter_Body", bm, mats["body"], coll))

    # chrome wind-guard hood: thin D-shaped shell around the wheel end
    bm = bmesh.new()
    t = 0.35
    outer = _d_outline(A + 0.02, B + 0.02, HOOD_X0, +1)
    inner = _d_outline(A - t, B - t, HOOD_X0 + t, +1, n=64)
    # match vertex counts
    if len(inner) != len(outer):
        k = np.linspace(0, len(inner) - 1, len(outer))
        inner = np.stack([np.interp(k, np.arange(len(inner)), inner[:, 0]),
                          np.interp(k, np.arange(len(inner)), inner[:, 1])], 1)
    vo = _loft(bm, [(outer, HOOD_Z0), (outer, HOOD_Z1)], False, False)
    vi = _loft(bm, [(inner, HOOD_Z0), (inner, HOOD_Z1)], False, False)
    n = len(outer)
    for i in range(n):  # top and bottom rims
        bm.faces.new((vo[1][i], vo[1][(i + 1) % n], vi[1][(i + 1) % n], vi[1][i]))
        bm.faces.new((vo[0][(i + 1) % n], vo[0][i], vi[0][i], vi[0][(i + 1) % n]))
    for f in bm.faces:
        f.smooth = True
    objs.append(_mesh_obj("Lighter_Hood", bm, mats["chrome"], coll))

    # gas button (fork) at the -X end, top surface at 50 mm
    bm = bmesh.new()
    rings = _fillet_rings(lambda d: _d_outline(A - 0.6 - d, B - 0.6 - d, BUTTON_X1 - d, -1),
                          BODY_TOP - 0.6, BUTTON_TOP, 0.0001, 0.7)
    _loft(bm, rings)
    # grip ridges on top (flush-ish, 0.25 mm)
    for xr in (-4.0, -5.6, -7.2, -8.8):
        hw = (B - 1.6) * math.sqrt(max(0.0, 1 - (xr / (A - 1.3)) ** 2))
        _box(bm, xr - 0.35, xr + 0.35, -hw, hw, BUTTON_TOP - 0.2, BUTTON_TOP + 0.2)
    # fork arm reaching under the wheel to the nozzle
    _box(bm, BUTTON_X1 - 0.5, 4.4, -1.5, 1.5, 46.6, 49.2)
    objs.append(_mesh_obj("Lighter_Button", bm, mats["button"], coll))

    # nozzle
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.85, radius2=0.7, depth=2.4,
                          matrix=__import__("mathutils").Matrix.Translation((3.6, 0, 50.2)))
    objs.append(_mesh_obj("Lighter_Nozzle", bm, mats["brass"], coll))

    # knurled spark wheel: two knurled discs + spacer hub + axle
    bm = bmesh.new()
    teeth = 64
    prof = []
    for i in range(teeth * 3):
        k = i % 3
        prof.append(WHEEL_R if k == 0 else (WHEEL_R - 0.22 if k == 1 else WHEEL_R - 0.08))
    for y0, y1 in ((0.9, 2.9), (-2.9, -0.9)):
        _cylinder_y(bm, WHEEL_R, y0, y1, WHEEL_X, WHEEL_Z, n=teeth * 3, profile=prof)
    _cylinder_y(bm, 3.4, -0.9, 0.9, WHEEL_X, WHEEL_Z, n=48)
    _cylinder_y(bm, 0.8, -(B - 0.3) * 0.86, (B - 0.3) * 0.86, WHEEL_X, WHEEL_Z, n=24)
    objs.append(_mesh_obj("Lighter_Wheel", bm, mats["steel"], coll))

    for o in objs:
        o.scale = (0.001, 0.001, 0.001)
        if parent is not None:
            o.parent = parent
    return objs


def lighter_extents_mm():
    return {"semi_major": A, "semi_minor": B, "button_top": BUTTON_TOP,
            "wheel_top": WHEEL_Z + WHEEL_R, "height": 60.0}
