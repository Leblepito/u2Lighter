"""Headless Blender turntable pipeline for the lighter-case product.

Run from the project root (cwd), e.g.:
  blender -b --factory-startup --python pipeline/render/turntable.py -- --mode test
See pipeline/render/README.md for all modes and arguments.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mf3 import load_3mf                       # noqa: E402
from case_analysis import detect_cavity, clearance_check  # noqa: E402
import lighter_geo                              # noqa: E402

V2_CASE = "output/print/panter_kilif_v2.3mf"
ORIG_CASE = "work/3mf/3D/3dmodel.model"
STAND_LAYOUT = "output/report/stand_layout.json"
STAND_BASE = "output/print/stand_montajli.stl"
STAND_RGB = (0.66, 0.66, 0.65)   # light-grey PLA (sRGB)
STAND_CANDIDATES = ["output/preview/stand_dolu_montaj.glb", "output/preview/stand_dolu_montaj.stl"]
FPS = 24
SEAT_EPS_MM = 0.02    # lighter rests 0.02 mm above the detected floor (no coplanar contact)
LIGHT_SCALE = 1.0      # overridden by --light-scale


# --------------------------------------------------------------------------- args
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="turntable.py")
    p.add_argument("--scene", choices=["case", "stand"], default="case")
    p.add_argument("--case", default="auto",
                   help="case .3mf or .model; 'auto' = %s if it exists else %s" % (V2_CASE, ORIG_CASE))
    p.add_argument("--stand", default="auto", help="stand .glb/.gltf/.stl/.obj/.3mf ('auto' = output/preview/stand_dolu_montaj.*)")
    p.add_argument("--mode", default="test",
                   help="comma list of: analyze,test,bench,stills,frames")
    p.add_argument("--res", default="1440x1920")
    p.add_argument("--pct", type=int, default=100, help="resolution percentage")
    p.add_argument("--samples", type=int, default=0, help="max samples (0 = mode default)")
    p.add_argument("--noise", type=float, default=0.02, help="adaptive sampling threshold")
    p.add_argument("--seconds", type=float, default=9.0)
    p.add_argument("--frames", default="", help="frame range a-b (1-based), default all")
    p.add_argument("--start-phi", type=float, default=-30.0,
                   help="start angle (deg) of the front relative to camera; -30 = front 3/4 showing the head side")
    p.add_argument("--direction", type=int, default=-1, help="-1 clockwise seen from above (as reference), +1 ccw")
    p.add_argument("--profile", choices=["label", "constant"], default=None,
                   help="speed profile; default label (case) / constant (stand)")
    p.add_argument("--device", default="auto", help="auto|OPTIX|CUDA|CPU")
    p.add_argument("--tests-dir", default="work/render/tests")
    p.add_argument("--frames-dir", default=None)
    p.add_argument("--stills-dir", default="output/stills")
    p.add_argument("--tag", default="", help="suffix for test/still file names")
    p.add_argument("--no-lighter", action="store_true")
    p.add_argument("--stand-layout", default="", help="layout json (per-case transforms) for a custom --stand base")
    p.add_argument("--stand-lowpoly", action="store_true", help="use the GLB with low-poly cases instead of instancing")
    p.add_argument("--stand-no-lighters", action="store_true", help="instance cases without lighters")
    p.add_argument("--rotate-rig", choices=["auto", "on", "off"], default="auto",
                   help="orbit camera+lights+backdrop instead of the product (auto: on for stand)")
    p.add_argument("--save-blend", default="")
    p.add_argument("--margin", type=float, default=0.05, help="frame safety margin (fraction)")
    p.add_argument("--lens", type=float, default=100.0)
    p.add_argument("--elev", type=float, default=9.0, help="camera pitch down (deg)")
    p.add_argument("--light-scale", type=float, default=0.25, help="global multiplier for all studio lights")
    p.add_argument("--view", default="Khronos PBR Neutral", help="colour view transform (fallback AgX)")
    return p.parse_args(argv)


def log(*a):
    print("[turntable]", *a, flush=True)


# --------------------------------------------------------------------------- loading
def resolve_case(arg):
    if arg != "auto":
        return arg
    if os.path.exists(V2_CASE):
        return V2_CASE
    log("WARNING: %s not found, using original %s" % (V2_CASE, ORIG_CASE))
    return ORIG_CASE


def load_case_cached(path):
    st = os.stat(path)
    key = hashlib.md5(("%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime))).encode("utf-8")).hexdigest()[:12]
    cdir = "work/render/cache"
    os.makedirs(cdir, exist_ok=True)
    cfile = os.path.join(cdir, "case_%s.npz" % key)
    if os.path.exists(cfile):
        d = np.load(cfile, allow_pickle=True)
        r = {"verts": d["verts"].astype(np.float64), "tris": d["tris"], "mat": d["mat"],
             "materials": [tuple(x) for x in d["materials"].tolist()], "title": str(d["title"])}
        log("loaded cache", cfile, len(r["verts"]), "verts", len(r["tris"]), "tris")
        return r
    r = load_3mf(path)
    np.savez(cfile, verts=r["verts"].astype(np.float32), tris=r["tris"], mat=r["mat"],
             materials=np.array(r["materials"], dtype=object), title=r["title"])
    return r


def srgb_to_lin(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def make_case_material(name, rgba):
    lin = srgb_to_lin(rgba[:3])
    m = bpy.data.materials.new("Case_" + name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*lin, 1.0)
    dark = float(np.mean(lin)) < 0.05
    b.inputs["Roughness"].default_value = 0.5 if dark else 0.62
    b.inputs["Specular IOR Level"].default_value = 0.4
    # soft fibre-like sheen; keeps the crochet relief readable at grazing angles
    b.inputs["Sheen Weight"].default_value = 0.15 if dark else 0.3
    b.inputs["Sheen Roughness"].default_value = 0.45
    b.inputs["Sheen Tint"].default_value = (*lin, 1.0)
    return m


def mesh_from_arrays(name, verts_m, tris, mat_idx, materials, coll):
    me = bpy.data.meshes.new(name)
    nv, nt = len(verts_m), len(tris)
    me.vertices.add(nv)
    me.vertices.foreach_set("co", verts_m.astype(np.float32).ravel())
    me.loops.add(nt * 3)
    me.loops.foreach_set("vertex_index", tris.astype(np.int32).ravel())
    me.polygons.add(nt)
    me.polygons.foreach_set("loop_start", np.arange(0, nt * 3, 3, dtype=np.int32))
    try:
        me.polygons.foreach_set("loop_total", np.full(nt, 3, np.int32))
    except Exception:
        pass
    for mm in materials:
        me.materials.append(mm)
    me.polygons.foreach_set("material_index", mat_idx.astype(np.int32))
    me.update(calc_edges=True)
    try:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(35))
    except Exception as e:  # older API
        log("smooth shading fallback:", e)
        me.polygons.foreach_set("use_smooth", np.ones(nt, bool))
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


# --------------------------------------------------------------------------- studio
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    return sc


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = d.to_track_quat("-Z", "Y")


def build_studio(sc, product_height_m, product_size_m=0.065):
    # studio tuned for a ~65 mm product; scale distances (and power by s^2) for bigger ones
    S = max(1.0, product_size_m / 0.065)
    import bmesh
    coll = sc.collection
    # seamless cyclorama: floor (z=0) sweeping up into a wall behind the product (+Y)
    wall_y, R, top = 0.30 * S, 0.22 * S, 1.2 * S
    prof = [(-2.0 * S, 0.0), (wall_y - R, 0.0)]
    for k in range(1, 24):
        a = k / 24 * math.pi / 2
        prof.append((wall_y - R + R * math.sin(a), R - R * math.cos(a)))
    prof += [(wall_y, R), (wall_y, top)]
    bm = bmesh.new()
    xs = (-2.5 * S, 2.5 * S)
    rows = [[bm.verts.new((x, y, z)) for (y, z) in prof] for x in xs]
    for i in range(len(prof) - 1):
        f = bm.faces.new((rows[0][i], rows[0][i + 1], rows[1][i + 1], rows[1][i]))
        f.smooth = True
    me = bpy.data.meshes.new("Studio_Cyc")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:  # normals must point up / toward the product
        pass
    cyc = bpy.data.objects.new("Studio_Cyc", me)
    coll.objects.link(cyc)
    m = bpy.data.materials.new("Studio_Grey")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.15, 0.15, 0.15, 1)
    b.inputs["Roughness"].default_value = 0.85
    b.inputs["Specular IOR Level"].default_value = 0.2
    me.materials.append(m)
    # make sure the floor faces up
    me.update()
    if me.polygons[0].normal.z < 0:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        bm.free()

    # world: dim neutral fill
    w = bpy.data.worlds.new("Studio_World")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
    bg.inputs["Strength"].default_value = 0.12 * LIGHT_SCALE
    sc.world = w

    h = product_height_m
    tgt = (0.0, 0.0, 0.5 * h)

    def area(name, az_deg, el_deg, dist, size, power, shape="RECTANGLE", size_y=None, spread=None):
        ld = bpy.data.lights.new(name, "AREA")
        ld.shape = shape
        ld.size = size * S
        if size_y:
            ld.size_y = size_y * S
        ld.energy = power * S * S
        if spread:
            ld.spread = math.radians(spread)
        ob = bpy.data.objects.new(name, ld)
        coll.objects.link(ob)
        az, el = math.radians(az_deg), math.radians(el_deg)
        dist = dist * S
        # az measured from the camera direction (-Y), positive toward +X (camera right)
        ob.location = (dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az),
                       tgt[2] + dist * math.sin(el))
        look_at(ob, tgt)
        return ob

    k = LIGHT_SCALE
    area("Key", -42, 38, 0.55, 0.40, 22.0 * k, "RECTANGLE", 0.30)
    area("Fill", 55, 12, 0.65, 0.60, 7.0 * k, "RECTANGLE", 0.45)
    area("Rim", 155, 40, 0.45, 0.12, 14.0 * k, "RECTANGLE", 0.30)
    area("Top", 0, 85, 0.6, 0.5, 6.0 * k, "DISK")
    return cyc


# --------------------------------------------------------------------------- render setup
def setup_device(sc, want):
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    order = ["OPTIX", "CUDA"] if want in ("auto", "GPU") else ([want] if want != "CPU" else [])
    for dt in order:
        try:
            prefs.compute_device_type = dt
            try:
                prefs.refresh_devices()
            except Exception:
                prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == dt]
            if not devs:
                continue
            for d in prefs.devices:
                d.use = (d.type == dt)
            sc.cycles.device = "GPU"
            log("device:", dt, [d.name for d in devs])
            return dt
        except Exception as e:
            log("device", dt, "unavailable:", e)
    sc.cycles.device = "CPU"
    log("device: CPU")
    return "CPU"


def setup_render(sc, args, samples):
    rx, ry = (int(v) for v in args.res.lower().split("x"))
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = rx, ry, args.pct
    r.fps = FPS
    r.use_persistent_data = True
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.color_depth = "8"
    r.image_settings.compression = 15
    c = sc.cycles
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = args.noise
    c.use_denoising = True
    for k, v in (("denoiser", "OPENIMAGEDENOISE"), ("denoising_input_passes", "RGB_ALBEDO_NORMAL"),
                 ("denoising_prefilter", "ACCURATE"), ("denoising_quality", "HIGH"),
                 ("denoising_use_gpu", True)):
        try:
            setattr(c, k, v)
        except Exception as e:
            log("denoise opt", k, "skipped:", e)
    c.max_bounces = 8
    c.diffuse_bounces = 3
    c.glossy_bounces = 4
    c.transmission_bounces = 4
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = 8.0
    c.light_sampling_threshold = 0.01
    try:
        c.use_light_tree = True
    except Exception:
        pass
    vs = sc.view_settings
    try:
        vs.view_transform = args.view
    except Exception as e:
        log("view transform", args.view, "unavailable (%s), using AgX" % e)
        vs.view_transform = "AgX"
    vs.look = "None"
    vs.exposure = 0.0
    sc.display_settings.display_device = "sRGB"


# --------------------------------------------------------------------------- framing
def frame_camera(sc, cam, pts_local, args):
    """Choose camera distance + vertical shift so that the turntable's points fit
    the frame with safety margins at every rotation angle."""
    rx, ry = sc.render.resolution_x, sc.render.resolution_y
    cd = cam.data
    cd.lens = args.lens
    cd.sensor_fit = "VERTICAL"
    cd.sensor_height = 36.0
    sens_h = 36.0
    sens_w = sens_h * rx / ry
    el = math.radians(args.elev)
    fwd = np.array([0.0, math.cos(el), -math.sin(el)])
    up = np.array([0.0, math.sin(el), math.cos(el)])
    right = np.cross(fwd, up)
    if len(pts_local) > 40000:   # keep the silhouette-relevant points + a random sample
        rad = np.hypot(pts_local[:, 0], pts_local[:, 1])
        keep = np.unique(np.concatenate([
            np.argsort(rad)[-6000:], np.argsort(pts_local[:, 2])[-3000:], np.argsort(pts_local[:, 2])[:1000],
            np.random.default_rng(0).choice(len(pts_local), 30000, replace=False)]))
        pts_local = pts_local[keep]
    angs = np.radians(np.arange(0, 360, 3.0))
    P = []
    for a in angs:
        ca, sa = math.cos(a), math.sin(a)
        Rz = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
        P.append(pts_local @ Rz.T)
    P = np.concatenate(P)
    zc = 0.5 * (P[:, 2].max() + P[:, 2].min())
    tgt = np.array([0.0, 0.0, zc])
    m = args.margin
    mt, mb, mx = m, m + 0.02, m

    def extents(d):
        C = tgt - fwd * d
        rel = P - C
        z = rel @ fwd
        xn = (rel @ right) / z * cd.lens / (sens_w / 2)
        yn = (rel @ up) / z * cd.lens / (sens_h / 2)
        return np.abs(xn).max(), yn.min(), yn.max()

    lo, hi = 0.05, 5.0
    for _ in range(60):
        d = 0.5 * (lo + hi)
        xe, y0, y1 = extents(d)
        ok = xe <= 1 - 2 * mx and (y1 - y0) <= 2 - 2 * (mt + mb)
        if ok:
            hi = d
        else:
            lo = d
    d = hi
    xe, y0, y1 = extents(d)
    # vertical: centre the free space according to top/bottom margins
    target_center = ((1 - 2 * mt) + (-1 + 2 * mb)) / 2
    shift_ndc = (y0 + y1) / 2 - target_center
    cd.shift_y = shift_ndc / 2.0          # shift unit = frame height (portrait)
    cam.location = Vector((tgt - fwd * d).tolist())
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (math.pi / 2 - el, 0.0, 0.0)
    cd.clip_start, cd.clip_end = 0.01, 20.0
    info = {"distance_m": d, "lens_mm": cd.lens, "elev_deg": args.elev, "shift_y": cd.shift_y,
            "ndc_x_max": xe, "ndc_y": [y0 - 2 * cd.shift_y, y1 - 2 * cd.shift_y],
            "camera_z_m": float(cam.location.z)}
    log("framing:", json.dumps(info))
    return info


# --------------------------------------------------------------------------- animation profile
def speed_factor(phi_deg):
    """0.5 while the front faces the camera (|phi|<=45), 1.0 while the back does
    (|phi|>=135), C2-smooth (smootherstep) transition in between."""
    a = np.abs((np.asarray(phi_deg) + 180.0) % 360.0 - 180.0)
    x = np.clip((a - 45.0) / 90.0, 0, 1)
    s = x * x * x * (x * (x * 6 - 15) + 10)
    return 0.5 + 0.5 * s


def turn_profile(seconds, start_phi, direction, kind="label", fps=FPS):
    """Returns per-frame phi (deg, front-vs-camera angle) for frames 0..N-1 and stats.
    Turned angle Phi(t) satisfies Phi(0)=0, Phi(T)=360 exactly; omega = w0*s(phi)."""
    n = int(round(seconds * fps))
    G = 720000
    Phi = np.linspace(0.0, 360.0, G + 1)
    phi = start_phi + direction * Phi
    s = speed_factor(phi) if kind == "label" else np.ones_like(Phi)
    inv = 1.0 / s
    t = np.concatenate([[0.0], np.cumsum(0.5 * (inv[1:] + inv[:-1]) * np.diff(Phi))])
    w0 = t[-1] / seconds                        # deg/s at s = 1 ("normal speed")
    t = t / w0
    tf = np.arange(n) / fps
    Phi_f = np.interp(tf, t, Phi)
    stats = {"frames": n, "seconds": seconds, "normal_speed_deg_s": w0, "half_speed_deg_s": 0.5 * w0,
             "total_turn_deg": float(Phi[-1]), "start_phi_deg": start_phi, "direction": direction,
             "time_front_zone_s": float(np.sum(np.diff(t)[np.abs((phi[:-1] + 180) % 360 - 180) <= 45])),
             "time_back_zone_s": float(np.sum(np.diff(t)[np.abs((phi[:-1] + 180) % 360 - 180) >= 135])),
             "loop_step_deg_last_to_first": float(360.0 - Phi_f[-1]),
             "step_deg_first": float(Phi_f[1] - Phi_f[0])}
    return start_phi + direction * Phi_f, stats


# --------------------------------------------------------------------------- scenes
class Product:
    pass


def build_case_scene(sc, args):
    path = resolve_case(args.case)
    log("case model:", path)
    r = load_case_cached(path)
    v, t, mi = r["verts"], r["tris"], r["mat"].astype(np.int32)
    zmin = v[:, 2].min()
    if abs(zmin) > 1e-3:
        log("note: model zmin = %.4f mm, shifting to 0" % zmin)
        v = v - np.array([0, 0, zmin])
    t0 = time.time()
    cav = detect_cavity(v, t, mi, r["materials"])
    gmin, gmed = clearance_check(cav, lighter_geo.A, lighter_geo.B)
    cav["lighter_clearance_min_mm"], cav["lighter_clearance_median_mm"] = gmin, gmed
    cav["case_path"] = path
    log("cavity (%.1fs):" % (time.time() - t0),
        json.dumps({k: v_ for k, v_ in cav.items() if not k.startswith("_")}))
    os.makedirs("work/render", exist_ok=True)
    with open("work/render/cavity_detect.json", "w", encoding="utf-8") as f:
        json.dump({k: v_ for k, v_ in cav.items() if not k.startswith("_")}, f, indent=1)
    cross_check(cav)

    coll = sc.collection
    tt = bpy.data.objects.new("Turntable", None)
    coll.objects.link(tt)

    mats = [make_case_material(n, c) for n, c in r["materials"]]
    case = mesh_from_arrays("Case", v * 0.001, t, mi, mats, coll)

    # lighter placement (mm in case frame)
    ax = np.array(cav["axis_xy_mm"])
    wd = np.array(cav["major_dir"])
    lighter_objs = []
    if not args.no_lighter:
        lroot = bpy.data.objects.new("Lighter", None)
        coll.objects.link(lroot)
        lighter_objs = lighter_geo.build_lighter(coll, parent=lroot)
        lroot["seat_z_mm"] = cav["seat_z_mm"]
        lroot_xf = (Matrix.Translation((ax[0] * 1e-3, ax[1] * 1e-3, (cav["seat_z_mm"] + SEAT_EPS_MM) * 1e-3))
                    @ Matrix.Rotation(math.atan2(wd[1], wd[0]), 4, "Z"))
    # combined footprint -> rotation axis = centre of XY bbox (case + lighter)
    lpts = []
    if not args.no_lighter:
        e = lighter_geo.lighter_extents_mm()
        for k in range(36):
            a = 2 * math.pi * k / 36
            lpts.append(ax + wd * e["semi_major"] * math.cos(a)
                        + np.array([-wd[1], wd[0]]) * e["semi_minor"] * math.sin(a))
    allxy = np.concatenate([v[:, :2]] + ([np.array(lpts)] if lpts else []))
    ctr = 0.5 * (allxy.min(0) + allxy.max(0))
    off = Matrix.Translation((-ctr[0] * 1e-3, -ctr[1] * 1e-3, 0.0))
    # orient so that the model front is phi=0 when turntable rotation = theta_front
    fd = np.array(cav["front_dir"])
    theta_front = math.atan2(-1.0, 0.0) - math.atan2(fd[1], fd[0])   # camera sits at -Y
    case.parent = tt
    case.matrix_parent_inverse = off
    if not args.no_lighter:
        lroot.parent = tt
        lroot.matrix_parent_inverse = off @ lroot_xf

    # sample points for framing (turntable local, metres)
    step = max(1, len(v) // 60000)
    pts = (v[::step] - np.array([ctr[0], ctr[1], 0])) * 1e-3
    if not args.no_lighter:
        e = lighter_geo.lighter_extents_mm()
        top = []
        for k in range(24):
            a = 2 * math.pi * k / 24
            xy = ax + wd * e["semi_major"] * math.cos(a) + np.array([-wd[1], wd[0]]) * e["semi_minor"] * math.sin(a)
            top.append([xy[0], xy[1], cav["seat_z_mm"] + e["height"]])
        pts = np.concatenate([pts, (np.array(top) - np.array([ctr[0], ctr[1], 0])) * 1e-3])

    P = Product()
    P.root, P.theta_front, P.pts, P.height = tt, theta_front, pts, float(pts[:, 2].max())
    P.info = {"case_path": path, "title": r["title"], "verts": int(len(v)), "tris": int(len(t)),
              "materials": [m[0] for m in r["materials"]],
              "tri_count_per_material": np.bincount(mi, minlength=len(r["materials"])).tolist(),
              "rotation_axis_case_xy_mm": ctr.tolist(), "cavity": {k: v_ for k, v_ in cav.items() if not k.startswith("_")}}
    P.case, P.lighter = case, lighter_objs
    return P


def cross_check(cav):
    p = "output/report/case_metrics.json"
    if not os.path.exists(p):
        log("cross-check: %s not present" % p)
        return
    try:
        with open(p, encoding="utf-8") as f:
            ref = json.load(f)
    except Exception as e:
        log("cross-check: cannot read %s: %s" % (p, e))
        return
    flat = {}

    def walk(o, pre=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, pre + k + ".")
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            flat[pre[:-1]] = o
        elif isinstance(o, list) and len(o) <= 3 and all(isinstance(x, (int, float)) for x in o):
            flat[pre[:-1]] = o
    walk(ref)
    keys = [k for k in flat if any(s in k.lower() for s in ("cav", "sleeve", "pocket", "axis", "seat", "inner", "rim", "floor", "yuva"))]
    log("cross-check vs %s:" % p, json.dumps({k: flat[k] for k in keys}))
    with open("work/render/cavity_crosscheck.json", "w", encoding="utf-8") as f:
        json.dump({"render_detection": {k: v for k, v in cav.items() if not k.startswith("_")},
                   "case_metrics_relevant": {k: flat[k] for k in keys}}, f, indent=1)


def resolve_stand(arg):
    if arg != "auto":
        return arg
    for c in STAND_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("stand mesh not found (looked for %s); pass --stand PATH" % STAND_CANDIDATES)


def pla_material(name, srgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*srgb_to_lin(srgb), 1.0)
    b.inputs["Roughness"].default_value = 0.68
    b.inputs["Specular IOR Level"].default_value = 0.35
    return m


def add_layout_cases(sc, args, layout_path):
    """Instance the full-colour case (+ lighter) at every transform of the stand layout.
    All objects share one mesh per part (linked duplicates -> Cycles instancing). Units: mm."""
    with open(layout_path, encoding="utf-8") as f:
        lay = json.load(f)
    case_path = args.case if args.case != "auto" else lay.get("case_file", V2_CASE)
    if not os.path.exists(case_path):
        case_path = resolve_case("auto")
    r = load_case_cached(case_path)
    v, t, mi = r["verts"], r["tris"], r["mat"].astype(np.int32)
    v = v - np.array([0, 0, v[:, 2].min()])
    cav = detect_cavity(v, t, mi, r["materials"])
    log("stand: case %s, seat %.2f mm, %d instances" % (case_path, cav["seat_z_mm"], len(lay["cases"])))
    mats = [make_case_material(n, c) for n, c in r["materials"]]
    proto = mesh_from_arrays("CaseProto", v, t, mi, mats, sc.collection)   # mm
    parts = []
    if not args.stand_no_lighters:
        tmp = bpy.data.collections.new("_lighter_proto")
        parts = lighter_geo.build_lighter(tmp)
        for o in parts:
            o.scale = (1, 1, 1)
        wd = cav["major_dir"]
        L = (Matrix.Translation((cav["axis_xy_mm"][0], cav["axis_xy_mm"][1], cav["seat_z_mm"] + SEAT_EPS_MM))
             @ Matrix.Rotation(math.atan2(wd[1], wd[0]), 4, "Z"))
    objs = []
    for i, c in enumerate(lay["cases"]):
        M = Matrix([list(map(float, row)) for row in c["matrix_case_local_to_world"]])
        ob = proto if i == 0 else proto.copy()
        if i:
            sc.collection.objects.link(ob)
        ob.name = "Case_%d_%d" % (c.get("tier", 0), c.get("index", i))
        ob.matrix_world = M
        objs.append(ob)
        for p_ in parts:
            o2 = p_.copy()
            sc.collection.objects.link(o2)
            o2.matrix_world = M @ L @ p_.matrix_basis
            objs.append(o2)
    for p_ in parts:
        bpy.data.objects.remove(p_)
    return {"case_path": case_path, "instances": len(lay["cases"]), "lighters": bool(parts),
            "case_tris_per_instance": int(len(t))}


def build_stand_scene(sc, args):
    layout = None
    if args.stand == "auto" and not args.stand_lowpoly and os.path.exists(STAND_LAYOUT) and os.path.exists(STAND_BASE):
        path, layout = STAND_BASE, STAND_LAYOUT
    else:
        path = resolve_stand(args.stand)
        if args.stand_layout and os.path.exists(args.stand_layout):
            layout = args.stand_layout
    log("stand model:", path, "| layout:", layout)
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=os.path.abspath(path))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=os.path.abspath(path))
    elif ext in (".3mf", ".model"):
        r = load_3mf(path)
        mats = [make_case_material(n, c) for n, c in r["materials"]] or [make_case_material("PLA", (0.85, 0.85, 0.85, 1))]
        mesh_from_arrays("Stand", r["verts"] * 0.001, r["tris"], np.clip(r["mat"], 0, len(mats) - 1), mats, sc.collection)
    else:
        raise SystemExit("unsupported stand format: " + ext)
    base_objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not base_objs:
        raise SystemExit("no mesh imported from " + path)
    stand_mat = pla_material("Stand_PLA_LightGrey", STAND_RGB)
    if layout:   # base file has no colours -> matte light-grey PLA
        for o in base_objs:
            o.data.materials.clear()
            o.data.materials.append(stand_mat)
    lay_info = add_layout_cases(sc, args, layout) if layout else None
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    bpy.context.view_layer.update()
    co = np.concatenate([np.array([o.matrix_world @ Vector(c) for c in o.bound_box]) for o in new])
    size = co.max(0) - co.min(0)
    unit = 0.001 if size.max() > 2.0 else 1.0   # >2 "metres" -> file is in mm
    log("stand bbox size (file units):", size.tolist(), "unit scale:", unit)
    default_mat = None
    for o in new:
        if not o.data.materials:
            if default_mat is None:
                default_mat = stand_mat
            o.data.materials.append(default_mat)
    tt = bpy.data.objects.new("Turntable", None)
    sc.collection.objects.link(tt)
    ctr = 0.5 * (co.min(0) + co.max(0))
    off = Matrix.Scale(unit, 4) @ Matrix.Translation((-ctr[0], -ctr[1], -co[:, 2].min()))
    pts = []
    for o in new:
        if o.parent is None or o.parent not in new:
            mw = o.matrix_world.copy()
            o.parent = tt
            o.matrix_parent_inverse = off
            o.matrix_basis = mw
    bpy.context.view_layer.update()
    for o in new:
        me = o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        a = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", a)
        a = a.reshape(-1, 3)
        M = np.array(o.matrix_world)
        a = a @ M[:3, :3].T + M[:3, 3]
        step = max(1, len(a) // 20000)
        pts.append(a[::step])
    pts = np.concatenate(pts)
    P = Product()
    P.root, P.theta_front, P.pts, P.height = tt, 0.0, pts, float(pts[:, 2].max())
    P.info = {"stand_path": path, "layout": layout, "layout_instances": lay_info,
              "objects": len(new), "size_m": (size * unit).tolist()}
    P.case, P.lighter = None, []
    return P


# --------------------------------------------------------------------------- checks
def lighter_overlap_check(P):
    """BVH overlap between case and lighter (world space). 0 pairs = no interpenetration."""
    if P.case is None or not P.lighter:
        return None
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    case_bvh = BVHTree.FromObject(P.case, dg)
    res = {}
    for o in P.lighter:
        b = BVHTree.FromObject(o, dg)
        # FromObject builds in object space -> bring lighter into case space
        M = P.case.matrix_world.inverted() @ o.matrix_world
        me = o.data
        verts = [M @ v.co for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        b = BVHTree.FromPolygons(verts, polys)
        res[o.name] = len(case_bvh.overlap(b))
    log("lighter/case triangle overlaps:", res)
    return res


# --------------------------------------------------------------------------- render helpers
def set_phi(P, phi_deg):
    a = P.theta_front + math.radians(phi_deg)
    if getattr(P, "rig", None) is not None:      # static product, studio rig orbits instead
        P.rig.rotation_euler = (0.0, 0.0, -a)
    else:
        P.root.rotation_euler = (0.0, 0.0, a)


def render_still(sc, path):
    sc.render.filepath = os.path.abspath(path)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    log("rendered %s in %.1fs" % (path, dt))
    return dt


def main():
    args = parse_args()
    global LIGHT_SCALE
    LIGHT_SCALE = args.light_scale
    modes = [m.strip() for m in args.mode.split(",") if m.strip()]
    T0 = time.time()
    sc = reset_scene()
    P = build_case_scene(sc, args) if args.scene == "case" else build_stand_scene(sc, args)
    span = float(np.max(np.ptp(P.pts[:, :2], axis=0))) if len(P.pts) else 0.065
    build_studio(sc, P.height, max(span, P.height))
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    P.rig = None
    if args.rotate_rig == "on" or (args.rotate_rig == "auto" and args.scene == "stand"):
        # many heavy instances: keep them static (persistent data, no BVH/transform resync)
        # and orbit camera + lights + backdrop around the vertical axis instead (identical image)
        rig = bpy.data.objects.new("StudioRig", None)
        sc.collection.objects.link(rig)
        for o in list(sc.collection.objects):
            if o.type in ("LIGHT", "CAMERA") or o.name.startswith("Studio_Cyc"):
                o.parent = rig
        P.rig = rig
    dev = setup_device(sc, args.device)
    report = {"scene": args.scene, "device": dev, "product": P.info, "args": vars(args), "timings": {}}
    if P.case is not None:
        bpy.context.view_layer.update()
        report["lighter_case_overlaps"] = lighter_overlap_check(P)
    if "analyze" in modes:
        modes.remove("analyze")
    kind = args.profile or ("label" if args.scene == "case" else "constant")
    prefix = "" if args.scene == "case" else "stand_"

    for mode in modes:
        if mode == "test":
            setup_render(sc, args, args.samples or 48)
            report["framing"] = frame_camera(sc, cam, P.pts, args)
            os.makedirs(args.tests_dir, exist_ok=True)
            for name, phi in (("front", 0), ("34", args.start_phi), ("090", -90), ("back", 180), ("270", 90)):
                set_phi(P, phi)
                report["timings"]["test_" + name] = render_still(
                    sc, os.path.join(args.tests_dir, "%stest_%s%s.png" % (prefix, name, args.tag)))
        elif mode == "stills":
            setup_render(sc, args, args.samples or 512)
            report["framing"] = frame_camera(sc, cam, P.pts, args)
            os.makedirs(args.stills_dir, exist_ok=True)
            base = "panter_kilif" if args.scene == "case" else "stand_dolu"
            views = (("front", 0), ("3-4", args.start_phi), ("side", -90), ("back", 180)) if args.scene == "case"                 else (("front", 0), ("hero", args.start_phi))
            for name, phi in views:
                set_phi(P, phi)
                report["timings"]["still_" + name] = render_still(
                    sc, os.path.join(args.stills_dir, "%s_%s%s.png" % (base, name, args.tag)))
        elif mode in ("bench", "frames"):
            setup_render(sc, args, args.samples or 128)
            report["framing"] = frame_camera(sc, cam, P.pts, args)
            phis, stats = turn_profile(args.seconds, args.start_phi, args.direction, kind)
            report["profile"] = stats
            log("profile:", json.dumps(stats))
            tt = P.rig if getattr(P, "rig", None) is not None else P.root
            tt.animation_data_clear()
            for i, ph in enumerate(phis):
                set_phi(P, float(ph))
                tt.keyframe_insert("rotation_euler", index=2, frame=i + 1)
            fc = None
            ad = tt.animation_data
            try:
                fc = ad.action.fcurves[0]
            except Exception:
                try:  # Blender 5 layered actions
                    fc = ad.action.layers[0].strips[0].channelbags[0].fcurves[0]
                except Exception:
                    fc = None
            if fc is not None:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
            sc.frame_start, sc.frame_end = 1, len(phis)
            fdir = args.frames_dir or ("work/render/frames" if args.scene == "case" else "work/render/frames_stand")
            os.makedirs(fdir, exist_ok=True)
            if mode == "bench":
                frames = [1, 55]
                times = []
                for f in frames:
                    sc.frame_set(f)
                    times.append(render_still(sc, os.path.join("work/render", "bench_%04d.png" % f)))
                report["timings"]["bench"] = times
                est = times[-1] * len(phis) / 60.0
                log("BENCH: per-frame %s s (2nd frame w/ persistent data) -> estimate %.1f min for %d frames"
                    % (["%.1f" % x for x in times], est, len(phis)))
                report["timings"]["estimate_min"] = est
            else:
                a, b = 1, len(phis)
                if args.frames:
                    a, b = (int(x) for x in args.frames.split("-"))
                sc.frame_start, sc.frame_end = a, b
                sc.render.filepath = os.path.abspath(os.path.join(fdir, "frame_"))
                sc.render.use_overwrite = False
                sc.render.use_placeholder = False
                existing = sum(os.path.exists(os.path.join(fdir, "frame_%04d.png" % f)) for f in range(a, b + 1))
                log("frames %d-%d, %d already exist (skipped)" % (a, b, existing))
                ftimes = {}
                state = {}

                def pre(scene, *_):
                    state["t"] = time.time()

                def post(scene, *_):
                    dt = time.time() - state.get("t", time.time())
                    ftimes[scene.frame_current] = dt
                    with open(os.path.join(fdir, "_progress.log"), "a", encoding="utf-8") as f:
                        f.write("frame %d %.2fs\n" % (scene.frame_current, dt))
                bpy.app.handlers.render_pre.append(pre)
                bpy.app.handlers.render_post.append(post)
                t0 = time.time()
                bpy.ops.render.render(animation=True)
                report["timings"]["frames_total_s"] = time.time() - t0
                report["timings"]["frames_rendered"] = len(ftimes)
                if ftimes:
                    report["timings"]["frame_mean_s"] = float(np.mean(list(ftimes.values())))
        else:
            log("unknown mode", mode)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))
    report["timings"]["wall_total_s"] = time.time() - T0
    rp = "work/render/report_%s_%s.json" % (args.scene, "_".join(modes) or "analyze")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    log("report ->", rp, "total %.1fs" % report["timings"]["wall_total_s"])


if __name__ == "__main__":
    main()
