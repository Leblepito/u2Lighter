"""Task 2: build the modified case (v2): flat cut at z_cut, 3 mm plinth, stand-pin hole.

python build_case_v2.py [--config config.json] [--z-cut auto|<mm>] [--plinth-height 3.0]
                        [--hole-d 3.3] [--hole-chamfer 0.4] [--hole-mode auto|through|blind]
                        [--name panter_kilif_v2] [--skip-selfint] [--no-render]

Method: manifold3d (exact, robust mesh booleans, float64):
  case_cut = source ∩ {z >= z_cut}
  plinth   = extrude(filled outer outline of slice(z_cut), plinth_height) placed under z_cut
  v2       = (case_cut ∪ plinth) − (hole cylinder + 45° bottom chamfer cone)
  translate so min z = 0.  Per-triangle colours are carried through manifold face_id provenance.
"""
from __future__ import annotations

import argparse
import os
import time
import zipfile

import numpy as np
import manifold3d as m3
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import common as C
import meshutil as mu
from analyze_case import area_curve, auto_zcut


def section_colours(V, F, col, z):
    """Midpoints of source slice segments at z and the colour of the triangle producing each."""
    t = V[F]
    zmin, zmax = t[:, :, 2].min(1), t[:, :, 2].max(1)
    idx = np.nonzero((zmin <= z) & (zmax >= z))[0]
    segs = mu.slice_segments(V, F[idx], z)
    # slice_segments drops triangles touching only at a vertex; recompute mask the same way
    tt = V[F[idx]]
    d = tt[:, :, 2] - z
    d = np.where(np.abs(d) < 1e-9, 1e-9, d)
    s = (d > 0).sum(1)
    keep = (s == 1) | (s == 2)
    mids = segs.mean(1)
    return mids, col[idx[keep]]


def retag(M, base):
    mesh = M.to_mesh64()
    Vt = np.asarray(mesh.vert_properties)[:, :3]
    Ft = np.asarray(mesh.tri_verts)
    return C.to_manifold(Vt, Ft, face_id=base + np.arange(len(Ft)))


def circ_r(r, n):
    """Radius of an n-gon whose inscribed circle has radius r (so a printed hole is never undersized)."""
    return r / np.cos(np.pi / n)


def build(cfg, args):
    cc = cfg['case']
    d = C.load_source(cfg)
    V, F = d['V'], d['F']
    col = C.io3mf.triangle_colour_index(d)
    names = [m[0] for m in d['mats']]
    PEMBE = names.index(cc['plinth_default_colour'])
    log = {}
    t0 = time.time()
    src = C.to_manifold(V, F, face_id=np.arange(len(F)))
    assert str(src.status()) == 'Error.NoError', src.status()
    PL0, HO0 = 10_000_000, 20_000_000  # face_id ranges tag the origin of every output triangle

    # ---- z_cut
    zs, A, Af, P = area_curve(src, 0.0025, 2.0, 0.0125)
    zc_auto, _ = auto_zcut(zs, A, cc['growth_rate_threshold'])
    zc_arg = args.z_cut if args.z_cut is not None else cc['z_cut']
    layer = 0.12
    if str(zc_arg) == 'auto':
        z_cut = float(np.ceil(zc_auto / layer - 1e-6) * layer)
        zc_src = f'auto: knee of area curve at {zc_auto:.4f} mm, rounded up to a whole 0.12 mm layer'
    else:
        z_cut = float(zc_arg)
        zc_src = 'override'
    H = float(args.plinth_height if args.plinth_height is not None else cc['plinth_height'])
    log['z_cut'] = dict(value=z_cut, source=zc_src, knee=zc_auto)

    # ---- cut (volume removed below the plane)
    cut = src.trim_by_plane((0.0, 0.0, 1.0), z_cut)
    removed = src.volume() - cut.volume()
    del cut
    below = V[:, 2] < z_cut
    log['removed'] = dict(volume_mm3=round(removed, 3), max_depth_mm=round(z_cut - float(V[:, 2].min()), 4),
                          source_vertices_below_cut=int(below.sum()),
                          source_triangles_touching_below=int(np.any(below[F], axis=1).sum()))

    # ---- plinth footprint
    sec = C.cs_to_shapely(src.slice(z_cut))
    filled = C.fill_holes(sec)
    isl = [p for p in C.parts(filled) if p.area >= cc['plinth_min_island_area']]
    dropped = [p.area for p in C.parts(filled) if p.area < cc['plinth_min_island_area']]
    foot0 = unary_union(isl)
    # tiny outward offset so the plinth wall never coincides with the source surface's crossing line
    # (an exact coincidence yields zero-width knife-edge contacts in the boolean result)
    outset = float(cc.get('plinth_outset', 0.02))
    foot = foot0.buffer(outset, join_style='mitre', mitre_limit=3.0) if outset > 0 else foot0
    # drop micro-edges (they become sliver wall triangles): simplify within 3 µm
    foot = foot.simplify(0.003, preserve_topology=True)
    ev = []
    for p in C.parts(foot):
        xy = np.asarray(p.exterior.coords)
        ev.append(np.linalg.norm(np.diff(xy, axis=0), axis=1).min())
    contours = []
    for p in C.parts(foot):
        ext = np.asarray(p.exterior.coords)[:-1]
        if C._area(ext) < 0:
            ext = ext[::-1]
        contours.append(ext)
    cs = m3.CrossSection(contours, m3.FillRule.Positive)
    plinth = retag(m3.Manifold.extrude(cs, H).translate((0.0, 0.0, z_cut - H)), PL0)
    # everything of the source below z_cut must lie inside the plinth prism, otherwise the union
    # would leave bumps on the plinth wall
    lower = src.trim_by_plane((0.0, 0.0, -1.0), -z_cut)
    outside = (lower - plinth).volume()
    log['removed']['source_below_cut_outside_plinth_mm3'] = round(outside, 6)
    log['plinth'] = dict(height=H, footprint_area_mm2=round(foot.area, 2), islands=len(isl), outset_mm=outset,
                         exact_cut_outline_area_mm2=round(foot0.area, 3), footprint_vertices=int(sum(len(p.exterior.coords) - 1 for p in C.parts(foot))),
                         footprint_min_edge_mm=round(float(min(ev)), 5),
                         dropped_tiny_islands_mm2=[round(x, 4) for x in dropped],
                         footprint_bounds=np.round(foot.bounds, 3).tolist(),
                         material_section_area_at_cut=round(sec.area, 2))

    # ---- hole
    cav = C.find_cavity(C.cs_to_shapely(src.slice(25.0)))
    if cc['hole_axis'] == 'auto':
        ax_xy = np.array([cav.centroid.x, cav.centroid.y])
    else:
        ax_xy = np.array(cc['hole_axis'], float)
    hd = float(args.hole_d if args.hole_d is not None else cc['hole_diameter'])
    ch = float(args.hole_chamfer if args.hole_chamfer is not None else cc['hole_chamfer'])
    floor_total = H + 0.0  # source has no floor (open cavity) -> floor = plinth
    mode = args.hole_mode or 'auto'
    if mode == 'auto':
        mode = 'through' if floor_total <= cc['hole_through_if_floor_leq'] else 'blind'
    depth = floor_total if mode == 'through' else float(cc['hole_blind_depth'])
    n = 72
    r = circ_r(hd / 2, n)
    zb = z_cut - H
    top = z_cut + 0.6 if mode == 'through' else zb + depth
    cyl = m3.Manifold.cylinder(top - (zb - 0.5), r, r, n).translate((ax_xy[0], ax_xy[1], zb - 0.5))
    cone = m3.Manifold.cylinder(ch + 0.5, circ_r(hd / 2 + ch + 0.5, n), r, n).translate((ax_xy[0], ax_xy[1], zb - 0.5))
    hole = retag(cyl + cone, HO0)
    if mode == 'through':
        # hole must stay inside the cavity footprint above z_cut (no material of the case touched)
        assert cav.buffer(-0.5).contains(Point(*ax_xy).buffer(hd / 2 + ch)), 'hole would cut the sleeve wall'
    log['hole'] = dict(axis_xy=ax_xy.round(4).tolist(), model_diameter=hd, polygon_segments=n,
                       polygon_circumradius=round(r, 4), bottom_chamfer=ch, mode=mode,
                       depth=round(depth, 3), total_floor_under_lighter=floor_total,
                       rule=f"through if floor <= {cc['hole_through_if_floor_leq']} mm else blind {cc['hole_blind_depth']} mm")

    # ---- boolean: the plinth prism (top exactly at z_cut) volumetrically overlaps the source slab
    # 0..z_cut, so the union both files off the slab and fuses the plinth (no coplanar touching faces)
    res = (src + plinth) - hole
    st = str(res.status())
    shift = -(z_cut - H)
    res = res.translate((0.0, 0.0, shift))
    Vo, Fo, fid, toid = C.from_manifold(res)
    zmin = Vo[:, 2].min()
    Vo[:, 2] -= zmin  # exact zero
    Vo[np.abs(Vo[:, 2]) < 1e-9, 2] = 0.0
    shift -= zmin
    origin = np.where(fid < len(F), 0, np.where((fid >= PL0) & (fid < HO0), 1, np.where(fid >= HO0, 2, 3)))
    log['boolean'] = dict(status=st, seconds=round(time.time() - t0, 1), z_shift_applied=shift,
                          method='(source ∪ plinth_prism) − hole, manifold3d float64',
                          triangles_by_origin={k: int((origin == i).sum()) for i, k in enumerate(['source', 'plinth', 'hole', 'other'])})

    # ---- colours
    oc = np.full(len(Fo), PEMBE, np.int64)
    from_src = origin == 0
    oc[from_src] = col[fid[from_src]]
    t = Vo[Fo]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    nn = nrm / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-30)
    from_pl = origin == 1
    side = from_pl & (np.abs(nn[:, 2]) < 0.5)
    inherit = cc['plinth_side_colour'] == 'inherit'
    if inherit and side.any():
        mids, mc = section_colours(V, F, col, z_cut + 0.03)
        tree = cKDTree(mids)
        cen = t[side].mean(1)[:, :2]
        _, j = tree.query(cen)
        oc[side] = mc[j]
    other = origin == 3
    log['colours'] = dict(
        source_triangles_kept=int(from_src.sum()), plinth_triangles=int(from_pl.sum()),
        plinth_side_triangles=int(side.sum()),
        plinth_side_colours={names[i]: int((oc[side] == i).sum()) for i in range(len(names))},
        hole_triangles=int((origin == 2).sum()), other_origin_triangles=int(other.sum()),
        per_colour={names[i]: int((oc == i).sum()) for i in range(len(names))},
        rule='source triangles keep source p1/paint_color; plinth side walls inherit colour of nearest source triangle crossing z_cut+0.03; plinth bottom, cavity floor and pin hole = Pembe')
    return dict(V=Vo, F=Fo, col=oc, fid=fid, origin=origin,
                z_cut=z_cut, H=H, shift=shift, ax=ax_xy, hd=hd, ch=ch, mode=mode, depth=depth,
                foot=foot, names=names, mats=d['mats'], log=log, srcM=src, src=d)


def validate(b, cfg, skip_selfint=False):
    V, F, col = b['V'], b['F'], b['col']
    sd = b['src']
    Vs, Fs = sd['V'], sd['F']
    shift, z_cut, H = b['shift'], b['z_cut'], b['H']
    out = {}
    es = mu.edge_stats(F)
    lab, nsh = mu.shells(F, len(V))
    M = C.to_manifold(V, F)
    vol = mu.signed_volume(V, F)
    lo, hi = V.min(0), V.max(0)
    out['topology'] = dict(**es, shells=nsh, manifold3d_status=str(M.status()), genus=int(M.genus()),
                           signed_volume_mm3=round(vol, 2), source_volume_mm3=round(mu.signed_volume(Vs, Fs), 2),
                           vertices=len(V), triangles=len(F))
    out['bbox'] = dict(min=lo.round(4).tolist(), max=hi.round(4).tolist(), size=(hi - lo).round(4).tolist())
    # bottom flatness
    t = V[F]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2
    nz = nrm[:, 2] / (2 * ar + 1e-30)
    bot = (t[:, :, 2].max(1) == 0.0)
    near = (V[:, 2] > 0) & (V[:, 2] < 0.05)
    exp_bottom = b['foot'].area - np.pi * (b['hd'] / 2 + b['ch']) ** 2 if b['mode'] == 'through' else b['foot'].area - np.pi * (b['hd'] / 2 + b['ch']) ** 2
    out['footprint'] = dict(min_z=float(lo[2]), bottom_face_area_mm2=round(float(ar[bot].sum()), 3),
                            bottom_faces_all_facing_down=bool(np.all(nz[bot] < -0.999999)),
                            expected_area_footprint_minus_chamfer_mouth=round(exp_bottom, 3),
                            vertices_between_0_and_0p05=int(near.sum()), footprint_area=round(b['foot'].area, 2))
    # hole geometry from sections
    ax = b['ax']
    hole_rows = []
    for z in [0.0005, 0.2, 0.39, 0.5, 1.5, 2.5, H - 0.01, H + 0.01]:
        g = C.cs_to_shapely(M.slice(float(z)))
        best = None
        for p in C.parts(g):
            for r in p.interiors:
                h = Polygon(r)
                if h.contains(Point(*ax)) and (best is None or h.area < best.area):
                    best = h
        if best is None:
            # through to the cavity: the cavity hole contains the axis
            hole_rows.append(dict(z=z, hole=None))
            continue
        xy = np.asarray(best.exterior.coords)
        rr = np.linalg.norm(xy - ax, axis=1)
        # inscribed diameter: 2 * min distance from centre to the polygon boundary
        dmin = 2 * best.exterior.distance(Point(*ax))
        hole_rows.append(dict(z=z, centre=[round(best.centroid.x, 4), round(best.centroid.y, 4)],
                              inscribed_d=round(dmin, 4), max_d=round(2 * rr.max(), 4), area=round(best.area, 3)))
    cav_above = C.find_cavity(C.cs_to_shapely(M.slice(H + 0.01)))
    out['hole'] = dict(sections=hole_rows, mode=b['mode'], opens_into_cavity=bool(cav_above is not None and cav_above.contains(Point(*ax))),
                       axis=b['ax'].tolist())
    # cavity untouched
    cav_cmp = []
    for z in [0.5, 1, 5, 10, 25, 40, 48, 49.5]:
        if z <= z_cut:
            continue
        a_ = C.find_cavity(C.cs_to_shapely(b['srcM'].slice(float(z))))
        b_ = C.find_cavity(C.cs_to_shapely(M.slice(float(z + shift))))
        if a_ is None or b_ is None:
            cav_cmp.append(dict(z_src=z, missing=True))
            continue
        cav_cmp.append(dict(z_src=z, z_v2=round(z + shift, 4), area_src=round(a_.area, 4), area_v2=round(b_.area, 4),
                            sym_diff_mm2=round(a_.symmetric_difference(b_).area, 6),
                            bounds_v2=np.round(b_.bounds, 4).tolist()))
    # cavity floor flatness: section just above the floor inside the cavity has no material in cavity
    cav_ref = C.find_cavity(C.cs_to_shapely(b['srcM'].slice(25.0)))
    floor_ok = True
    g = C.cs_to_shapely(M.slice(H + 0.001))
    inner = cav_ref.buffer(-0.05)
    floor_ok = g.intersection(inner).area < 1e-6
    g2 = C.cs_to_shapely(M.slice(H - 0.001))
    floor_cover = g2.intersection(inner).area / inner.area
    out['cavity'] = dict(sections=cav_cmp, max_sym_diff_mm2=max(c.get('sym_diff_mm2', 0) for c in cav_cmp),
                         nothing_inside_cavity_above_floor=bool(floor_ok),
                         floor_coverage_just_below_seat=round(float(floor_cover), 5),
                         seat_z=H, floor_thickness=H,
                         wall_top_above_seat=round(50.0 - z_cut, 3) if True else None)
    # design above cut untouched: every source triangle fully above z_cut+1e-4 must appear unchanged
    zs = Vs[Fs][:, :, 2].min(1)
    above = np.nonzero(zs > z_cut + 1e-4)[0]
    src_mask = b['origin'] == 0
    fid = b['fid'][src_mask]
    tri_out = V[F[src_mask]]
    cnt = np.bincount(fid, minlength=len(Fs))
    sv = Vs.copy()
    sv[:, 2] += shift

    def canon(T):  # (k,3,3) -> rotation-invariant key: roll so the lexicographically smallest vertex is first
        key = T[:, :, 0] * 1e6 + T[:, :, 1] * 1e3 + T[:, :, 2]
        r = np.argmin(key, axis=1)
        idx3 = (np.arange(3)[None, :] + r[:, None]) % 3
        return np.take_along_axis(T, idx3[:, :, None], axis=1)

    single = above[cnt[above] == 1]
    first = np.full(len(Fs), -1, np.int64)
    first[fid[::-1]] = np.arange(len(fid))[::-1]
    a_out = canon(tri_out[first[single]])
    a_src = canon(sv[Fs[single]])
    same = np.all(np.abs(a_out - a_src) <= 1e-9, axis=(1, 2))
    unchanged = int(same.sum())
    changed = np.concatenate([above[cnt[above] != 1], single[~same]]).tolist()
    colour_ok = bool(np.all(col[src_mask] == C.io3mf.triangle_colour_index(sd)[fid]))
    ts = Vs[Fs[np.array(changed, np.int64)]] if changed else np.zeros((0, 3, 3))
    ch_area = np.linalg.norm(np.cross(ts[:, 1] - ts[:, 0], ts[:, 2] - ts[:, 0]), axis=1) / 2 if len(ts) else np.zeros(0)
    out['design_preservation'] = dict(source_triangles_fully_above_cut=int(len(above)), unchanged_in_v2=unchanged,
                                      changed_or_missing=len(changed), changed_sample=changed[:10],
                                      changed_max_area_mm2=float(ch_area.max()) if len(ch_area) else 0.0,
                                      changed_note='missing triangles with zero area are degenerate source triangles dropped by the boolean (no geometric change)',
                                      source_colour_preserved_on_all_source_triangles=colour_ok)
    # self intersection
    if not skip_selfint:
        p = C.rp('work', 'cache', 'v2_si.npz')
        np.savez(p, V=V, F=F)
        j = C.rp('work', 'cache', 'selfint_v2.json')
        C.run_blender('blender_selfintersect.py', [p, j])
        si = C.json.load(open(j))
        out['self_intersections'] = si['intersecting_pairs']
    return out, M


def overhang_clusters(V, F, M, thr_from_vertical=60.0, cell=1.0, min_area=2.0):
    """Cluster down-facing faces steeper than thr (deg from vertical) on a voxel grid (6-connectivity)."""
    from scipy import ndimage
    t = V[F]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2
    nz = nrm[:, 2] / (2 * ar + 1e-30)
    cz = t[:, :, 2].mean(1)
    m = (nz < -np.cos(np.radians(90 - thr_from_vertical))) & (t[:, :, 2].max(1) > 1e-6)
    c = t[m].mean(1)
    a_ = ar[m]
    if not len(c):
        return []
    g0 = np.floor(c.min(0) / cell).astype(int)
    ijk = np.floor(c / cell).astype(int) - g0
    grid = np.zeros(ijk.max(0) + 1, bool)
    grid[tuple(ijk.T)] = True
    labl, nl = ndimage.label(grid)
    L = labl[tuple(ijk.T)]
    area = np.bincount(L, weights=a_, minlength=nl + 1)
    regs = []
    for k in np.nonzero(area >= min_area)[0]:
        if k == 0:
            continue
        mm = L == k
        cc = c[mm]
        p0 = cc[np.argmin(cc[:, 2])]
        below = None
        if M is not None:
            hits = M.ray_cast((float(p0[0]), float(p0[1]), float(p0[2]) - 0.05), (float(p0[0]), float(p0[1]), -1.0))
            below = 'model surface at z=%.1f' % hits[0].position[2] if hits else 'build plate (clear path)'
        regs.append(dict(area_mm2=round(float(area[k]), 1), z_range=[round(float(cc[:, 2].min()), 1), round(float(cc[:, 2].max()), 1)],
                         xy_centre=np.round(cc[:, :2].mean(0), 1).tolist(), below_lowest_point=below))
    regs.sort(key=lambda r: -r['area_mm2'])
    return regs


def print_check(b, M, cfg):
    """Overhangs, thin walls, support recommendation for Bambu A1."""
    V, F, col = b['V'], b['F'], b['col']
    t = V[F]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2
    nn = nrm / (2 * ar[:, None] + 1e-30)
    cz = t[:, :, 2].mean(1)
    out = {}
    lo, hi = V.min(0), V.max(0)
    size = hi - lo
    out['fits_A1_256'] = bool(np.all(size <= 256))
    ov = (nn[:, 2] < -np.cos(np.radians(45))) & (cz > 1e-6)
    bands = [(0, 3.2), (3.2, 5), (5, 15), (15, 30), (30, 45), (45, 70)]
    out['overhang_gt45_area_mm2_by_z'] = {f'{a}-{b_}': round(float(ar[ov & (cz >= a) & (cz < b_)].sum()), 2) for a, b_ in bands}
    ov60 = (nn[:, 2] < -np.cos(np.radians(30))) & (cz > 1e-6)
    out['overhang_gt60_area_mm2_total'] = round(float(ar[ov60].sum()), 2)
    out['support_threshold_note'] = ('Bambu Studio default support threshold angle = 30° from horizontal, i.e. faces whose '
                                     'normal is within 30° of straight down (overhang > 60° from vertical) get supports')
    out['steep_overhang_regions_v2'] = overhang_clusters(V, F, M, 60.0)
    src = b['src']
    Vs = src['V'].copy()
    Vs[:, 2] += b['shift']
    out['steep_overhang_regions_source_shifted'] = overhang_clusters(Vs, src['F'], None, 60.0)[:6]
    # plinth / case junction ledge: how far the case outline overhangs the plinth top edge in the first mm
    foot = b['foot']
    H = b['H']
    led = []
    for dz in [0.12, 0.24, 0.5, 1.0, 2.0]:
        g = C.fill_holes(C.cs_to_shapely(M.slice(H + dz)))
        diff = g.difference(foot.buffer(0))
        ext = 0.0
        for p in C.parts(diff):
            xy = np.asarray(p.exterior.coords)
            ext = max(ext, max(foot.exterior.distance(Point(*q)) if hasattr(foot, 'exterior') else 0 for q in xy[::max(1, len(xy) // 200)]))
        led.append(dict(z_above_plinth=dz, area_outside_plinth_mm2=round(diff.area, 2), max_outward_offset_mm=round(ext, 3)))
    out['case_outline_vs_plinth'] = led
    # wall thickness: inward ray from triangle centroids (sample)
    rng = np.random.default_rng(0)
    idx = rng.choice(len(F), size=min(40000, len(F)), replace=False, p=ar / ar.sum())
    th = []
    for i in idx:
        p0 = t[i].mean(0) - nn[i] * 1e-4
        p1 = p0 - nn[i] * 8.0
        h = M.ray_cast(tuple(map(float, p0)), tuple(map(float, p1)))
        th.append(float(np.linalg.norm(np.asarray(h[0].position) - p0)) + 1e-4 if h else np.nan)
    th = np.array(th, float)
    out['wall_thickness_samples'] = dict(n=int(np.isfinite(th).sum()))
    return out, th, idx


def transfer_colours(Vd, Fd, V, F, col, k=12):
    """Colour of each decimated triangle = colour of the nearest exact triangle whose normal agrees (dot > 0.5)."""
    def cn(Vx, Fx):
        t = Vx[Fx]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        return t.mean(1), n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-30)
    c0, n0 = cn(np.asarray(V, float), F)
    c1, n1 = cn(np.asarray(Vd, float), np.asarray(Fd, np.int64))
    tree = cKDTree(c0)
    _, jj = tree.query(c1, k=k)
    dots = np.einsum('ikc,ic->ik', n0[jj], n1)
    good = dots > 0.5
    first = np.where(good.any(1), good.argmax(1), 0)
    return col[jj[np.arange(len(jj)), first]]


def write_outputs(b, cfg, name):
    V, F, col = b['V'], b['F'], b['col']
    pc = [C.PALETTE[n][1] for n in b['names']]
    paint = [pc[c] for c in col]
    mats = [(n, h) for n, h in b['mats']]
    objs = [dict(name='Panter YENİ YAKI v2', V=V, F=F, mat=col, paint=paint,
                 transform=[float(x) for x in b['src']['transform']])]
    p3 = C.rp('output', 'print', f'{name}.3mf')
    ms = C.io3mf.model_settings_for(['Panter - YENİ YAKI v2'], [[0]])
    C.io3mf.write_3mf(p3, objs, mats, metadata_dir=C.rp(cfg['source_metadata_dir']),
                      title='Panter - YENİ YAKI v2', application=str(b['src']['application']), model_settings_xml=ms)
    np.savez(C.rp('work', 'cache', 'case_v2.npz'), V=V, F=F, col=col, ax=b['ax'], H=b['H'], z_cut=b['z_cut'],
             foot=np.asarray(C.parts(b['foot'])[0].exterior.coords))
    ps = C.rp('output', 'print', f'{name}.stl')
    C.io3mf.write_stl_binary(ps, V, F)
    # decimated preview
    import fast_simplification
    target = cfg['case']['decimate_target_tris']
    Vd, Fd = fast_simplification.simplify(V.astype(np.float32), F.astype(np.int32), target_reduction=1 - target / len(F))
    pp = C.rp('work', 'preview', 'case_v2_lowpoly.stl')
    C.io3mf.write_stl_binary(pp, Vd, Fd)
    cd = transfer_colours(Vd, Fd, V, F, col)
    np.savez(C.rp('work', 'preview', 'case_v2_lowpoly.npz'), V=Vd, F=Fd, col=cd)
    return p3, ps, pp, len(Fd)


def reread_3mf(p3):
    """Round-trip check: parse the written 3MF exactly like the source."""
    tmp = C.rp('work', 'cache', 'v2_roundtrip.model')
    with zipfile.ZipFile(p3) as z:
        names = z.namelist()
        with open(tmp, 'wb') as f:
            f.write(z.read('3D/3dmodel.model'))
    d = C.io3mf.read_model(tmp)
    os.remove(tmp)
    return names, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config')
    ap.add_argument('--z-cut', dest='z_cut')
    ap.add_argument('--plinth-height', type=float)
    ap.add_argument('--hole-d', type=float)
    ap.add_argument('--hole-chamfer', type=float)
    ap.add_argument('--hole-mode', choices=['auto', 'through', 'blind'])
    ap.add_argument('--name', default='panter_kilif_v2')
    ap.add_argument('--skip-selfint', action='store_true')
    ap.add_argument('--no-render', action='store_true')
    args = ap.parse_args()
    cfg = C.load_config(args.config)
    b = build(cfg, args)
    print(C.json.dumps(b['log'], indent=1, default=C._jdef, ensure_ascii=False))
    val, M = validate(b, cfg, args.skip_selfint)
    print(C.json.dumps(val, indent=1, default=C._jdef, ensure_ascii=False))
    pc, th, idx = print_check(b, M, cfg)
    p3, ps, pp, nd = write_outputs(b, cfg, args.name)
    names, rd = reread_3mf(p3)
    rt = dict(zip_entries=names, vertices=int(len(rd['V'])), triangles=int(len(rd['F'])),
              attr_sets=rd['attr_sets'], materials=[list(m) for m in rd['materials']],
              p1_equals_built=bool(np.all(rd['p1'] == b['col'])),
              paint_matches_p1=bool(np.all(C.io3mf.paint_state(rd) == rd['p1'] + 1)),
              max_vertex_roundoff=float(np.abs(rd['V'] - b['V']).max()))
    th_f = th[np.isfinite(th)]
    pc['wall_thickness_mm'] = dict(method='inward ray from 40k area-weighted random surface points to the next surface',
                                   p01=round(float(np.percentile(th_f, 1)), 3), p05=round(float(np.percentile(th_f, 5)), 3),
                                   p50=round(float(np.percentile(th_f, 50)), 3), min=round(float(th_f.min()), 3),
                                   frac_below_0p4=round(float((th_f < 0.4).mean()), 4), frac_below_0p8=round(float((th_f < 0.8).mean()), 4))
    pc.pop('_ray_distance_units', None)
    # sleeve wall (radial) thickness around the cavity at several heights
    cav_ref = C.find_cavity(C.cs_to_shapely(b['srcM'].slice(25.0)))
    sw = []
    for z in [2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 48, 49.5]:
        g = C.cs_to_shapely(M.slice(float(z + b['shift'])))
        ring = cav_ref.exterior
        best, where = np.inf, None
        for p in C.parts(g):
            if p.distance(ring) > 0.05:
                continue
            ext = p.exterior
            for s in np.linspace(0, ring.length, 720, endpoint=False):
                q = ring.interpolate(s)
                dd = ext.distance(q)
                if dd < best:
                    best, where = dd, (round(q.x, 2), round(q.y, 2))
        sw.append(dict(z_src=z, min_radial_wall=round(best, 3), at_xy=where))
    pc['sleeve_min_radial_wall'] = sw
    report = dict(build=b['log'], validation=val, print_check=pc, roundtrip_3mf=rt,
                  outputs=dict(threemf=p3, stl=ps, preview=pp, preview_tris=nd))
    C.save_json(C.rp('output', 'report', 'case_v2_validation.json'), report)
    print(C.json.dumps(dict(print_check=pc, roundtrip=rt), indent=1, default=C._jdef, ensure_ascii=False))
    # th sample save for histogram
    np.save(C.rp('work', 'cache', 'v2_thickness.npy'), th)
    # ---- figures
    out = C.rp('output', 'report')
    fig, axs = plt.subplots(1, 2, figsize=(14, 6))
    Mt = M.translate((-b['ax'][0], -b['ax'][1], 0.0))
    # XZ plane through the axis: rotate +90 about X -> 2D (x, -z);  YZ plane: rotate +90 about Y -> 2D (z, y)
    for ax, rot, mapf, lab in [(axs[0], (90.0, 0.0, 0.0), lambda u, v: (u, -v), 'XZ kesiti (y = pim ekseni), x yatay'),
                               (axs[1], (0.0, 90.0, 0.0), lambda u, v: (v, u), 'YZ kesiti (x = pim ekseni), y yatay (-Y = ön)')]:
        g = C.cs_to_shapely(Mt.rotate(rot).slice(0.0))
        for p in C.parts(g):
            xs, ys = mapf(np.asarray(p.exterior.xy[0]), np.asarray(p.exterior.xy[1]))
            ax.fill(xs, ys, color='#F28AB4', lw=0.4, ec='k')
            for r in p.interiors:
                xs, ys = mapf(np.asarray(r.xy[0]), np.asarray(r.xy[1]))
                ax.fill(xs, ys, color='w', lw=0.4, ec='k')
        ax.axhline(b['H'], color='b', ls=':', lw=0.8, label=f"oturma düzlemi z={b['H']:.2f}")
        ax.axhline(0, color='k', lw=0.8)
        ax.set_ylim(-1, 14); ax.set_aspect('equal'); ax.grid(alpha=.3); ax.set_title(lab); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(out, 'v2_dikey_kesitler.png'), dpi=120); plt.close(fig)
    if not args.no_render:
        np.savez(C.rp('work', 'cache', 'v2_render.npz'), V=b['V'].astype(np.float32), F=b['F'].astype(np.int32), mat=b['col'].astype(np.int32))
        cols = [C.hex_rgb(m[1][:7]) for m in b['mats']]
        views = [('alt', [0, 0, -1], [0, -1, 0]), ('alt_izo', [-0.7, -1.0, -0.8], [0, 0, 1]),
                 ('on_-Y', [0, -1, 0], [0, 0, 1]), ('izo', [-0.6, -1, 0.7], [0, 0, 1]),
                 ('arka_alt_izo', [0.8, 1.0, -0.6], [0, 0, 1])]
        C.render_views([dict(npz=C.rp('work', 'cache', 'v2_render.npz'), colors=cols)], views, out, 'v2')


if __name__ == '__main__':
    main()
