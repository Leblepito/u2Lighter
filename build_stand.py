"""Task 3: parametric display stand (3 tiers, 8/4/2 pins, hex-jointed column, tilted sign).

python build_stand.py [--config config.json] [--pins 8,4,2] [--pitch 80] [--no-render]

Requires work/cache/case_v2.npz (written by build_case_v2.py). All geometry is exact CSG (manifold3d).
Coordinates: world Z up, stand axis = (0,0), front of the stand (sign face, notch marks) = -Y.
Case local frame = the v2 file's object frame (pin-hole axis at x=y=0, bottom at z=0, figure front = -Y).
"""
from __future__ import annotations

import argparse
import math
import os

import numpy as np
import manifold3d as m3
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, Point
from shapely import affinity
from shapely.ops import unary_union

import common as C
import meshutil as mu

SQ3 = math.sqrt(3.0)


# ----------------------------------------------------------------------------- primitives
def hex_prism(af, h, z0=0.0):
    r = af / SQ3
    return m3.Manifold.cylinder(h, r, r, 6).translate((0, 0, z0))


def hex_frustum(af0, af1, h, z0=0.0):
    return m3.Manifold.cylinder(h, af0 / SQ3, af1 / SQ3, 6).translate((0, 0, z0))


def cyl(r, h, z0=0.0, n=96, r2=None):
    return m3.Manifold.cylinder(h, r, r if r2 is None else r2, n).translate((0, 0, z0))


def pin(p, x, y, z_top):
    d, h, ch = p['pin_diameter'], p['pin_height'], p['pin_top_chamfer']
    r = d / 2
    body = cyl(r, h - ch + 0.4, z_top - 0.3, 48)  # overlaps the tip by 0.1
    tip = cyl(r, ch, z_top + h - ch, 48, r2=r - ch)
    return (body + tip).translate((x, y, 0))


def socket_cutter(p):
    """Hex socket opening downward at z=0 with a 6-sided pyramid ceiling (support-free)."""
    af = p['hex_across_flats'] + 2 * p['joint_clearance']
    depth = p['spigot_length'] - p['plate_thickness'] + 0.5  # spigot protrudes (L - T); +0.5 end gap
    r = af / SQ3
    body = hex_prism(af, depth + 0.01, -0.01)
    roof = m3.Manifold.cylinder(r, r, 0.0, 6).translate((0, 0, depth))
    return body + roof, depth


def spigot(p, z0, length):
    af = p['hex_across_flats']
    ch = 0.6
    return hex_prism(af, length - ch + 0.11, z0 - 0.01) + hex_frustum(af, af - 2 * ch, ch, z0 + length - ch)  # 0.1 overlap


def plate(p, radius, pins_xy, z_pins, hole=True, front_notch=True):
    T = p['plate_thickness']
    n = p['circle_segments'] * 2
    ch = 0.8
    body = cyl(radius, T - ch, 0, n) + cyl(radius, ch, T - ch, n, r2=radius - ch)
    if hole:
        af = p['hex_across_flats'] + 2 * p['joint_clearance']
        body = body - hex_prism(af, T + 2, -1)
    if front_notch:  # small V notch on the rim at -Y = assembly index mark ("ön")
        tri = m3.CrossSection([np.array([[-1.6, 0.0], [1.6, 0.0], [0.0, 2.2]])])
        notch = m3.Manifold.extrude(tri, T + 2).translate((0, 0, -1)).translate((0, -radius - 0.01, 0))
        body = body - notch
    for (x, y) in pins_xy:
        body = body + pin(p, x, y, z_pins)
    return body


# ----------------------------------------------------------------------------- case data
def load_case():
    d = np.load(C.rp('work', 'cache', 'case_v2.npz'))
    V, F, col = d['V'], d['F'], d['col']
    ax = d['ax']
    V = V.copy()
    V[:, 0] -= ax[0]
    V[:, 1] -= ax[1]
    return V, F, col, ax


def case_shapes(V, F):
    M = C.to_manifold(V, F)
    sil = C.cs_to_shapely(M.project())          # whole-case top-view silhouette (pin-hole at origin)
    sil = C.fill_holes(sil)
    foot = C.fill_holes(C.cs_to_shapely(M.slice(0.01)))  # plinth footprint
    height = float(V[:, 2].max())
    return M, sil, foot, height


def place(geom, R, theta_deg):
    """Case local -> world for a case on ring radius R at polar angle theta (front faces radially outward)."""
    phi = theta_deg + 90.0
    g = affinity.rotate(geom, phi, origin=(0, 0))
    t = math.radians(theta_deg)
    return affinity.translate(g, R * math.cos(t), R * math.sin(t))


def case_matrix(R, theta_deg, z):
    phi = math.radians(theta_deg + 90.0)
    t = math.radians(theta_deg)
    c, s = math.cos(phi), math.sin(phi)
    return np.array([[c, -s, 0, R * math.cos(t)], [s, c, 0, R * math.sin(t)], [0, 0, 1, z], [0, 0, 0, 1.0]])


def solve_ring(sil, n, theta0, p, obstacle=None):
    """Smallest radius (0.5 mm steps) with neighbour gap >= min_case_gap and column/obstacle gap."""
    thetas = [theta0 + 360.0 * k / n for k in range(n)]
    col_r = p['column_diameter'] / 2
    for R2 in np.arange(10.0, 200.0, 0.5):
        P = [place(sil, R2, th) for th in thetas]
        gaps = [P[k].distance(P[(k + 1) % n]) for k in range(n)] if n > 1 else [np.inf]
        if n == 2:
            gaps = [P[0].distance(P[1])]
        colgap = min(g.distance(Point(0, 0)) for g in P) - col_r
        obgap = min(g.distance(obstacle) for g in P) if obstacle is not None else np.inf
        if min(gaps) >= p['min_case_gap'] and colgap >= p['min_column_gap'] and obgap >= p['min_case_gap']:
            return float(R2), thetas, float(min(gaps)), float(colgap), float(obgap)
    raise RuntimeError('ring not solvable')


# ----------------------------------------------------------------------------- sign holder
def sign_parts(p, z_base):
    """Top piece (column + holder) in assembled coords with its bottom at z_base; panel assembled.
    Panel centre sits sign_gap_above_top_plate above the top plate's top surface (= z_base)."""
    W, Hs, Ts = p['sign_width'], p['sign_height'], p['sign_thickness']
    a = p['sign_tilt_deg']
    cl = p['joint_clearance']
    ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
    zc = z_base + p['sign_gap_above_top_plate']
    # panel frame: s along panel height (u = (0, sa, ca)), n through thickness (0, ca, -sa); top leans back (+Y)
    y_be, z_be = 0.0 - Hs / 2 * sa, zc - Hs / 2 * ca  # bottom-edge centre
    slot_w = Ts + 2 * cl
    wall = 2.5
    depth = 12.0
    bw = 36.0

    def frame(M):
        return M.rotate((-a, 0.0, 0.0)).translate((0.0, y_be, z_be))
    block = frame(m3.Manifold.cube((bw, slot_w + 2 * wall, depth + 3.0)).translate((-bw / 2, -(slot_w / 2 + wall), -3.0)))
    slot = frame(m3.Manifold.cube((W + 20, slot_w, depth + 5)).translate((-(W + 20) / 2, -slot_w / 2, 0.0)))
    panel = frame(m3.Manifold.cube((W, Ts, Hs)).translate((-W / 2, -Ts / 2, 0.0)))
    zb = block.bounding_box()[2]  # lowest z of the tilted block
    r = p['column_diameter'] / 2
    trans_h = max(16.0, (bw / 2 - r) / math.tan(math.radians(40)))  # hull flanks <= 40 deg from vertical
    z_h = zb - trans_h
    column = cyl(r, z_h - z_base + 0.5, z_base, p['circle_segments'])
    disc = cyl(r, 0.5, z_h, p['circle_segments'])
    hull = m3.Manifold.batch_hull([disc, block])
    sock, sdepth = socket_cutter(p)
    top = (column + hull) - slot - sock.translate((0, 0, z_base))
    info = dict(panel_centre=[0.0, 0.0, zc], panel_bottom_edge_centre=[0.0, y_be, z_be], slot_width=slot_w,
                slot_depth=depth, holder_width=bw, transition_height=trans_h, tilt_deg=a,
                top_piece_height=float(top.bounding_box()[5] - z_base), hull_start_z=float(z_h), block_lowest_z=float(zb))
    return top, panel, info


# ----------------------------------------------------------------------------- checks
def part_check(name, M):
    mesh = M.to_mesh64()
    V = np.asarray(mesh.vert_properties)[:, :3]
    F = np.asarray(mesh.tri_verts).astype(np.int64)
    es = mu.edge_stats(F)
    lab, nsh = mu.shells(F, len(V))
    t = V[F]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2
    nz = nrm[:, 2] / (2 * ar + 1e-30)
    lo, hi = V.min(0), V.max(0)
    down = (nz < -1e-6) & (t[:, :, 2].max(1) > lo[2] + 1e-6)
    ang = np.degrees(np.arccos(np.clip(-nz[down], -1, 1)))  # angle of face normal from straight down
    over_from_vertical = 90 - ang
    return dict(name=name, triangles=len(F), watertight=es['boundary_edges'] == 0 and es['nonmanifold_edges'] == 0,
                oriented=es['directed_duplicate_edges'] == 0, shells=nsh, status=str(M.status()), genus=int(M.genus()),
                volume_mm3=round(M.volume(), 1), min_z=round(float(lo[2]), 6),
                bbox_size=(hi - lo).round(2).tolist(),
                max_overhang_deg_from_vertical=round(float(over_from_vertical.max()), 1) if down.any() else 0.0,
                overhang_area_gt45_mm2=round(float(ar[down][over_from_vertical > 45.01].sum()), 2),
                fits_bed=bool(np.all((hi - lo)[:2] <= 256) and (hi - lo)[2] <= 256)), V, F


def mesh_of(M):
    mesh = M.to_mesh64()
    return np.asarray(mesh.vert_properties)[:, :3].copy(), np.asarray(mesh.tri_verts).astype(np.int64)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config')
    ap.add_argument('--pins', help='comma list, bottom->top, e.g. 8,4,2')
    ap.add_argument('--pitch', type=float)
    ap.add_argument('--no-render', action='store_true')
    a = ap.parse_args()
    cfg = C.load_config(a.config)
    p = cfg['stand']
    if a.pins:
        for t, n in zip(p['tiers'], [int(x) for x in a.pins.split(',')]):
            t['pins'] = n
    if a.pitch:
        p['tier_pitch'] = a.pitch
    T = p['plate_thickness']
    pitch = p['tier_pitch']
    rep = dict(params=p)

    V, F, col, ax = load_case()
    Mcase, sil, foot, hcase = case_shapes(V, F)
    sb = sil.bounds
    fb = foot.bounds
    rep['case'] = dict(height=round(hcase, 3), silhouette_bounds_rel_hole=np.round(sb, 3).tolist(),
                       footprint_bounds_rel_hole=np.round(fb, 3).tolist(),
                       silhouette_area=round(sil.area, 1), footprint_area=round(foot.area, 1),
                       note='bounds are [xmin, ymin, xmax, ymax] relative to the pin-hole axis; -Y = figure front')

    # tier z levels (plate top surfaces)
    ntier = len(p['tiers'])
    z_top = [T + k * pitch for k in range(ntier)]

    # top tier first (needs the sign holder as obstacle)
    top_piece, panel, sinfo = sign_parts(p, z_top[-1])
    zlo, zhi = z_top[-1], z_top[-1] + hcase + 1.0
    ob_parts = []
    for Mo in (top_piece, panel):
        cut = Mo.trim_by_plane((0, 0, 1), zlo).trim_by_plane((0, 0, -1), -zhi)
        if not cut.is_empty():
            ob_parts.append(C.fill_holes(C.cs_to_shapely(cut.project())))
    obstacle = unary_union(ob_parts) if ob_parts else None

    theta0 = {8: -90.0, 4: -45.0, 2: -90.0, 1: -90.0}
    tiers = []
    for k, tdef in enumerate(p['tiers']):
        n = tdef['pins']
        th0 = theta0.get(n, -90.0)
        ob = obstacle if k == ntier - 1 else None
        R, thetas, gap, colgap, obgap = solve_ring(sil, n, th0, p, ob)
        feet = [place(foot, R, th) for th in thetas]
        rmax = max(max(math.hypot(*c) for c in f.exterior.coords) for f in feet)
        rplate = math.ceil(rmax + p['plate_margin'])
        tiers.append(dict(name=tdef['name'], pins=n, ring_radius=R, thetas_deg=thetas, plate_radius=float(rplate),
                          plate_diameter=float(2 * rplate), z_plate_top=z_top[k], neighbour_gap_min=round(gap, 2),
                          column_gap_min=round(colgap, 2), obstacle_gap_min=None if ob is None else round(obgap, 2),
                          footprint_max_radius=round(rmax, 2)))
    # plates must shrink upward; enforce monotonic (bigger lower plate)
    for k in range(ntier - 2, -1, -1):
        if tiers[k]['plate_radius'] <= tiers[k + 1]['plate_radius']:
            tiers[k]['plate_radius'] = tiers[k + 1]['plate_radius'] + 5
            tiers[k]['plate_diameter'] = 2 * tiers[k]['plate_radius']
    assert tiers[0]['plate_diameter'] < 250, 'bottom plate too large for spec'

    # vertical clearance between case tops and the plate above
    for k in range(ntier - 1):
        tiers[k]['vertical_clearance_case_top_to_plate_above'] = round(z_top[k + 1] - T - (z_top[k] + hcase), 3)
        tiers[k]['vertical_clearance_lighter_top_to_plate_above'] = round(
            z_top[k + 1] - T - (z_top[k] + 3.0 + cfg['lighter']['height_total']), 3)
        # is each lower-tier cavity reachable from above (outside the plate above)?
        cav_inner = tiers[k]['ring_radius'] - cfg['lighter']['base_short'] / 2 - 0.3
        tiers[k]['cavity_inner_edge_radius'] = round(cav_inner, 2)
        tiers[k]['lighter_insertable_in_place'] = bool(cav_inner > tiers[k + 1]['plate_radius'])
    tiers[-1]['sign_holder_widening_start_z_minus_case_top'] = round(sinfo['hull_start_z'] - (z_top[-1] + hcase), 2)
    tiers[-1]['sign_panel_lowest_z_minus_case_top'] = round(panel.bounding_box()[2] - (z_top[-1] + hcase), 2)

    # ---------------- parts (assembled coordinates)
    parts = {}
    sock, sdepth = socket_cutter(p)
    for k, t in enumerate(tiers):
        pins_xy = [(t['ring_radius'] * math.cos(math.radians(th)), t['ring_radius'] * math.sin(math.radians(th)))
                   for th in t['thetas_deg']]
        z0 = z_top[k] - T
        if k == 0:
            pl = plate(p, t['plate_radius'], pins_xy, T, hole=False)
            pl = pl + spigot(p, T, p['spigot_length'] - T)       # bottom plate spigot (into segment 1 socket)
        else:
            pl = plate(p, t['plate_radius'], pins_xy, T, hole=True)
        parts[f'plaka_{k + 1}_{t["name"]}'] = pl.translate((0, 0, z0))
    r = p['column_diameter'] / 2
    for k in range(ntier - 1):
        zb, ze = z_top[k], z_top[k + 1] - T
        seg = cyl(r, ze - zb, zb, p['circle_segments']) + spigot(p, ze, p['spigot_length'])
        seg = seg - sock.translate((0, 0, zb))
        parts[f'kolon_{k + 1}'] = seg
    parts['ust_parca_tabela_tutucu'] = top_piece
    parts['tabela_panel'] = panel

    # ---------------- interference: stand parts pairwise
    names = list(parts)
    inter = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            v = (parts[names[i]] ^ parts[names[j]]).volume()
            if v > 1e-6:
                inter.append((names[i], names[j], round(v, 4)))
    rep['stand_part_overlaps_mm3'] = inter
    # joint clearances (radial play) for the record
    rep['joints'] = dict(type='hexagonal spigot/socket, anti-rotation', spigot_af=p['hex_across_flats'],
                         socket_and_plate_hole_af=p['hex_across_flats'] + 2 * p['joint_clearance'],
                         clearance_per_side=p['joint_clearance'], spigot_length_above_shoulder=p['spigot_length'],
                         socket_depth=round(sdepth, 2), engagement_in_socket=round(p['spigot_length'] - T, 2),
                         socket_roof='6-sided pyramid (faces ~41 deg from vertical), support-free')

    # ---------------- cases: placement + collision checks against stand and each other
    print('rings solved', flush=True)
    Mlow = Mcase.simplify(0.05)  # proxy for collision checks (tolerance 0.05 mm)
    layout = []
    case_ms = []
    for k, t in enumerate(tiers):
        for i, th in enumerate(t['thetas_deg']):
            Mx = case_matrix(t['ring_radius'], th, z_top[k])
            layout.append(dict(tier=k + 1, tier_name=t['name'], index=i, theta_deg=round(th, 3), ring_radius=t['ring_radius'],
                               pin_xy=[round(t['ring_radius'] * math.cos(math.radians(th)), 4),
                                       round(t['ring_radius'] * math.sin(math.radians(th)), 4)],
                               z_seat_plate_top=z_top[k], rotation_z_deg=round(th + 90.0, 3),
                               matrix_case_local_to_world=Mx.round(6).tolist()))
            case_ms.append(Mlow.transform(np.ascontiguousarray(Mx[:3, :])))
    stand_all = m3.Manifold.batch_boolean(list(parts.values()), m3.OpType.Add)
    print('collision checks...', flush=True)
    col_rows = []
    for ci, cm in enumerate(case_ms):
        v = (cm ^ stand_all).volume()
        col_rows.append((ci, round(v, 4)))
    cc_rows = []
    for i in range(len(case_ms)):
        for j in range(i + 1, len(case_ms)):
            if abs(layout[i]['tier'] - layout[j]['tier']) > 1:
                continue
            bi, bj = case_ms[i].bounding_box(), case_ms[j].bounding_box()
            if any(bi[k + 3] < bj[k] or bj[k + 3] < bi[k] for k in range(3)):
                continue  # bounding boxes disjoint
            cc_rows.append((i, j, round((case_ms[i] ^ case_ms[j]).volume(), 4)))
    # 2D (top-view silhouette) gaps are lower bounds of the true 3D gaps
    sil_w = []
    for L in layout:
        sil_w.append(place(sil, L['ring_radius'], L['theta_deg']))
    rep['case_vs_stand'] = dict(method='case proxy = v2 simplified (0.05 mm); boolean intersection volume with the union of all stand parts',
                                max_intersection_mm3=max(r_[1] for r_ in col_rows), per_case=col_rows,
                                column_gap_2d_min=min(t['column_gap_min'] for t in tiers),
                                note='0 expected: plinth bottom only touches the plate top; pin sits in the 3.3 hole with 0.15 radial play')
    rep['case_vs_case'] = dict(method='boolean intersection volume for every pair whose bounding boxes overlap (pairs with disjoint boxes cannot intersect; adjacent tiers are z-disjoint); '
                                      'clearance = 2D top-view silhouette gap within a tier (lower bound of the 3D gap)',
                               max_intersection_mm3=max((r_[2] for r_ in cc_rows), default=0.0), pairs_checked=len(cc_rows),
                               min_gap_mm=min(t['neighbour_gap_min'] for t in tiers if t['pins'] > 1))
    # pin-in-hole check
    rep['pin_in_hole'] = dict(pin_d=p['pin_diameter'], hole_d_model=cfg['case']['hole_diameter'],
                              radial_play=round((cfg['case']['hole_diameter'] - p['pin_diameter']) / 2, 3),
                              pin_height=p['pin_height'], hole_depth=3.0,
                              pin_top_below_lighter_seat=round(3.0 - p['pin_height'], 3))

    # ---------------- print orientation copies + checks
    out_dir = C.rp('output', 'print', 'stand')
    os.makedirs(out_dir, exist_ok=True)
    print_parts = {}
    checks = []
    for nm, Mp in parts.items():
        if nm == 'tabela_panel':
            Mq = m3.Manifold.cube((p['sign_width'], p['sign_height'], p['sign_thickness'])).translate(
                (-p['sign_width'] / 2, -p['sign_height'] / 2, 0))
            assert abs(Mq.volume() - Mp.volume()) < 1e-6
        else:
            bb = Mp.bounding_box()
            Mq = Mp.translate((0, 0, -bb[2]))
        bb = Mq.bounding_box()
        Mq = Mq.translate((-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, 0))
        print_parts[nm] = Mq
        ck, Vp, Fp = part_check(nm, Mq)
        checks.append(ck)
        C.io3mf.write_stl_binary(os.path.join(out_dir, f'{nm}.stl'), Vp, Fp)
    rep['parts'] = checks

    # ---------------- plates packing for the 3MF (A1 256x256)
    bed, mg = p['bed_size'], p['bed_margin']
    order = sorted(print_parts, key=lambda n: -max(print_parts[n].bounding_box()[3] - print_parts[n].bounding_box()[0],
                                                     print_parts[n].bounding_box()[4] - print_parts[n].bounding_box()[1]))
    plates = []  # list of list of (name, x, y)
    occ = []
    for nm in order:
        fp = C.fill_holes(C.cs_to_shapely(print_parts[nm].project()))
        placed = False
        for pi in range(len(plates)):
            for (x, y) in _candidates(fp, bed, mg):
                g = affinity.translate(fp, x, y)
                if all(g.distance(o) >= 5.0 for o in occ[pi]):
                    plates[pi].append((nm, x, y))
                    occ[pi].append(g)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            plates.append([(nm, bed / 2, bed / 2)])
            occ.append([affinity.translate(fp, bed / 2, bed / 2)])
    stride = bed * 1.2  # Bambu Studio lays out plates on a grid with 1/5 gap (LOGICAL_PART_PLATE_GAP)
    ncols = math.ceil(math.sqrt(len(plates)))
    objs, plate_objs, oi = [], [], 0
    pindex = 2  # Fildisi
    for pi, pl in enumerate(plates):
        ox, oy = (pi % ncols) * stride, -(pi // ncols) * stride
        ids = []
        for (nm, x, y) in pl:
            Vp, Fp = mesh_of(print_parts[nm])
            objs.append(dict(name=nm, V=Vp, F=Fp, mat=None, paint=None, pindex=pindex,
                             transform=[1, 0, 0, 0, 1, 0, 0, 0, 1, ox + x, oy + y, 0]))
            ids.append(oi)
            oi += 1
        plate_objs.append(ids)
    ms = C.io3mf.model_settings_for([o['name'] for o in objs], plate_objs, extruder=pindex + 1)
    C.io3mf.write_3mf(C.rp('output', 'print', 'stand', 'stand_tumu.3mf'), objs, [(n, h) for n, h in _mats()],
                      metadata_dir=C.rp(cfg['source_metadata_dir']), title='Panter stand (kit)',
                      application='u2Lighter pipeline', model_settings_xml=ms)
    rep['plates_3mf'] = [[dict(part=nm, x=round(x, 1), y=round(y, 1)) for (nm, x, y) in pl] for pl in plates]

    # ---------------- assembled outputs
    Vs, Fs = [], []
    off = 0
    for nm, Mp in parts.items():
        Vp, Fp = mesh_of(Mp)
        Vs.append(Vp)
        Fs.append(Fp + off)
        off += len(Vp)
    Va, Fa = np.concatenate(Vs), np.concatenate(Fs)
    C.io3mf.write_stl_binary(C.rp('output', 'print', 'stand_montajli.stl'), Va, Fa)
    lp = np.load(C.rp('work', 'preview', 'case_v2_lowpoly.npz'))
    Vl, Fl = lp['V'].astype(np.float64), lp['F'].astype(np.int64)
    Vl[:, 0] -= ax[0]
    Vl[:, 1] -= ax[1]
    if 'col' in lp.files:
        coll = lp['col'].astype(np.int64)
    else:
        tree = cKDTree(V[F].mean(1))
        _, jj = tree.query(Vl[Fl].mean(1))
        coll = col[jj]
    write_glb(C.rp('output', 'preview', 'stand_dolu_montaj.glb'), parts, Vl, Fl, coll, layout)
    np.savez(C.rp('work', 'cache', 'stand_render.npz'), V=Va.astype(np.float32), F=Fa.astype(np.int32))

    rep['tiers'] = tiers
    rep['sign'] = sinfo
    rep['overall'] = dict(height=round(float(stand_all.bounding_box()[5]), 2),
                          bottom_plate_diameter=tiers[0]['plate_diameter'],
                          assembly_order=[
                              '1. plaka_1_alt masaya (spigot yukarı), ön çentik öne (-Y).',
                              '2. kolon_1: alt soket plaka_1 altıgen pimine geçirilir.',
                              '3. plaka_2_orta: altıgen deliği kolon_1 üst pimine, çentik öne; kolon_1 omzuna oturur.',
                              '4. kolon_2: soketi plaka_2 üstünden çıkan kolon_1 pimine geçirilir.',
                              '5. plaka_3_ust: kolon_2 pimine, çentik öne.',
                              '6. ust_parca_tabela_tutucu: kolon_2 pimine; yuva yüzü öne (-Y).',
                              '7. tabela_panel yuvaya alttan oturana kadar itilir (gerekirse 1 damla yapıştırıcı).',
                              '8. Kılıflar pimlere: ön yüz (etiket) dışa bakacak; önce alt kat, sonra orta, en son üst.'])
    C.save_json(C.rp('output', 'report', 'stand_params.json'), rep)
    C.save_json(C.rp('output', 'report', 'stand_layout.json'),
                dict(frame='case local = panter_kilif_v2 object frame (pin-hole axis at x=y=0, bottom z=0, front -Y); '
                           'world = assembled stand (axis at x=y=0, table z=0, stand front -Y). world = M @ local',
                     case_file='output/print/panter_kilif_v2.3mf', preview_case='work/preview/case_v2_lowpoly.stl',
                     cases=layout))
    print(C.json.dumps(dict(case=rep['case'], tiers=tiers, sign=sinfo, overlaps=inter, case_vs_stand={k: v for k, v in rep['case_vs_stand'].items() if k != 'per_case'},
                            case_vs_case=rep['case_vs_case'], parts=checks, plates=rep['plates_3mf'],
                            overall=rep['overall']['height']), indent=1, default=C._jdef, ensure_ascii=False))

    if not a.no_render:
        out = C.rp('output', 'report')
        np.savez(C.rp('work', 'cache', 'case_low_render.npz'), V=Vl.astype(np.float32), F=Fl.astype(np.int32), mat=coll.astype(np.int32))
        cols = [C.hex_rgb(C.PALETTE[n][0]) for n in ['Pembe', 'Siyah', 'Fildisi', 'Sari']]
        meshes = [dict(npz=C.rp('work', 'cache', 'stand_render.npz'), color=[0.93, 0.88, 0.80])]
        for L in layout:
            meshes.append(dict(npz=C.rp('work', 'cache', 'case_low_render.npz'), colors=cols,
                               matrix=L['matrix_case_local_to_world']))
        views = [('on', [0, -1, 0.25], [0, 0, 1]), ('izo', [-0.8, -1, 0.6], [0, 0, 1]), ('ust', [0, 0, 1], [0, 1, 0]),
                 ('yan', [1, 0, 0.1], [0, 0, 1])]
        C.render_views(meshes, views, out, 'stand_dolu', res=(1100, 1300))
        C.render_views([dict(npz=C.rp('work', 'cache', 'stand_render.npz'), color=[0.93, 0.88, 0.80])],
                       [('izo', [-0.8, -1, 0.6], [0, 0, 1]), ('on', [0, -1, 0.0], [0, 0, 1])], out, 'stand_bos', res=(1000, 1200))


def _candidates(fp, bed, mg):
    b = fp.bounds
    w, h = b[2] - b[0], b[3] - b[1]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    xs = np.arange(mg + w / 2, bed - mg - w / 2 + 1e-9, 4.0)
    ys = np.arange(mg + h / 2, bed - mg - h / 2 + 1e-9, 4.0)
    pts = [(x - cx, y - cy) for y in ys for x in xs]
    pts.sort(key=lambda q: -((q[0] + cx - bed / 2) ** 2 + (q[1] + cy - bed / 2) ** 2))  # corners first
    return pts


def _mats():
    return [(n, C.PALETTE[n][0] + 'FF') for n in ['Pembe', 'Siyah', 'Fildisi', 'Sari']]


def write_glb(path, parts, Vl, Fl, coll, layout):
    import trimesh
    sc = trimesh.Scene()
    stand_mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[238, 225, 204, 255], roughnessFactor=0.7, name='stand_Fildisi')
    for nm, Mp in parts.items():
        Vp, Fp = mesh_of(Mp)
        tm = trimesh.Trimesh(Vp, Fp, process=False)
        tm.visual = trimesh.visual.TextureVisuals(material=stand_mat)
        sc.add_geometry(tm, geom_name=nm, node_name=nm)
    names = ['Pembe', 'Siyah', 'Fildisi', 'Sari']
    subs = {}
    for ci, n in enumerate(names):
        m = coll == ci
        if not m.any():
            continue
        Fi = Fl[m]
        used, inv = np.unique(Fi, return_inverse=True)
        tm = trimesh.Trimesh(Vl[used], inv.reshape(-1, 3), process=False)
        rgb = [int(round(255 * x)) for x in C.hex_rgb(C.PALETTE[n][0])]
        tm.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=rgb + [255], roughnessFactor=0.8, name=f'kilif_{n}'))
        subs[n] = tm
    for li, L in enumerate(layout):
        Mx = np.array(L['matrix_case_local_to_world'])
        base = f"kilif_t{L['tier']}_{L['index']}"
        for n, tm in subs.items():
            if li == 0:  # geometry stored once, instanced by node transforms
                sc.add_geometry(tm, geom_name=f'kilif_{n}', node_name=f'{base}_{n}', transform=Mx)
            else:
                sc.graph.update(frame_to=f'{base}_{n}', frame_from=sc.graph.base_frame, matrix=Mx, geometry=f'kilif_{n}')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sc.export(path)


if __name__ == '__main__':
    main()
