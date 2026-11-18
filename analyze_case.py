"""Task 1: analyse the source case mesh -> output/report/case_metrics.json + diagnostic PNGs.

python analyze_case.py [--config config.json] [--no-render]
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon

import common as C
import meshutil as mu


def area_curve(M, z0, z1, step):
    zs = np.arange(z0, z1 + 1e-9, step)
    A, Af, P = [], [], []
    for z in zs:
        g = C.cs_to_shapely(M.slice(float(z)))
        A.append(g.area)
        f = C.fill_holes(g)
        Af.append(f.area)
        P.append(f.length)
    return zs, np.array(A), np.array(Af), np.array(P)


def auto_zcut(zs, A, thr, window=0.1):
    """Lowest z where the bottom-edge rounding has ended: forward-difference dA/dz over `window`
    drops below thr (mm^2 per mm) and stays below for the next 0.2 mm."""
    step = zs[1] - zs[0]
    w = max(1, int(round(window / step)))
    rate = (A[w:] - A[:-w]) / (zs[w:] - zs[:-w])
    k2 = max(1, int(round(0.2 / step)))
    for i in range(len(rate) - k2):
        if np.all(rate[i:i + k2] < thr):
            return float(zs[i]), rate
    return float(zs[-1]), rate


def underside_heightmap(V, F, zmax=3.0, cell=0.1, sub=5):
    t = V[F]
    m = t[:, :, 2].min(1) < zmax
    t = t[m]
    # barycentric samples
    ij = [(i, j) for i in range(sub + 1) for j in range(sub + 1 - i)]
    B = np.array([(i / sub, j / sub, 1 - (i + j) / sub) for i, j in ij])
    pts = np.einsum('kb,tbc->tkc', B, t).reshape(-1, 3)
    lo = pts[:, :2].min(0) - cell
    idx = np.floor((pts[:, :2] - lo) / cell).astype(int)
    shape = idx.max(0) + 2
    H = np.full(shape, np.inf)
    np.minimum.at(H, (idx[:, 0], idx[:, 1]), pts[:, 2])
    return H, lo, cell


def wall_tops(M, cav, z_from, z_to, step=0.05, offset=0.5, nring=720):
    ring = cav.buffer(offset, join_style=2).exterior
    s = np.linspace(0, ring.length, nring, endpoint=False)
    rxy = np.array([ring.interpolate(x).coords[0] for x in s])
    cx, cy = cav.centroid.x, cav.centroid.y
    minx, miny, maxx, maxy = cav.bounds
    probes = {'on_-Y': Point(cx, miny - offset), 'arka_+Y': Point(cx, maxy + offset),
              'sol_-X': Point(minx - offset, cy), 'sag_+X': Point(maxx + offset, cy)}
    tops = {k: None for k in probes}
    full_top = None
    frac_rows = []
    alive = {k: True for k in probes}
    full_alive = True
    for z in np.arange(z_from, z_to, step):
        g = C.cs_to_shapely(M.slice(float(z)))
        inside = C.shapely.contains_xy(g, rxy[:, 0], rxy[:, 1])
        frac_rows.append((float(z), float(inside.mean())))
        if full_alive and inside.all():
            full_top = float(z)
        elif full_alive:
            full_alive = False
        for k, p in probes.items():
            if alive[k] and g.contains(p):
                tops[k] = float(z)
            elif alive[k]:
                alive[k] = False
    return tops, full_top, frac_rows


def min_wall_around_cavity(g, cav, n=720):
    """Min distance from cavity boundary points to the outer boundary of the material polygon (radial wall)."""
    best = np.inf
    ring = cav.exterior
    for p in C.parts(g):
        if not p.buffer(0.05).contains(Point(cav.centroid.x, cav.centroid.y)) and not p.intersects(ring.buffer(0.05)):
            continue
        ext = p.exterior
        for s in np.linspace(0, ring.length, n, endpoint=False):
            q = ring.interpolate(s)
            best = min(best, ext.distance(q))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=None)
    ap.add_argument('--no-render', action='store_true')
    a = ap.parse_args()
    cfg = C.load_config(a.config)
    out = C.rp('output', 'report')
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    d = C.load_source(cfg)
    V, F = d['V'], d['F']
    col = io_col = C.io3mf.triangle_colour_index(d)
    pstate = C.io3mf.paint_state(d)
    mats = d['mats']
    names = [m[0] for m in mats]
    met = {}
    met['source'] = dict(file='lighter-Panter-YENI-YAKI-A1.3mf', object_name=d['obj_attrs'].get('name'),
                         application=str(d['application']), build_transform=list(map(float, d['transform'])),
                         units='millimeter', triangle_attribute_sets=d['attr_sets'])
    met['counts'] = dict(vertices=int(len(V)), triangles=int(len(F)))
    met['colours'] = {names[i]: dict(hex=mats[i][1], triangles=int((col == i).sum())) for i in range(len(mats))}
    agree = bool(np.all(pstate == (col + 1)))
    met['colour_encoding'] = dict(
        per_triangle_pid_p1=True, object_default=f"pid={d['obj_attrs'].get('pid')} pindex={d['obj_attrs'].get('pindex')}",
        bambu_paint_color_present=True, paint_color_matches_p1=agree,
        paint_codes={'4': 'filament 1 Pembe', '8': 'filament 2 Siyah', '0C': 'filament 3 Fildisi', '1C': 'filament 4 Sari'})
    lo, hi = V.min(0), V.max(0)
    met['bbox'] = dict(min=lo.round(4).tolist(), max=hi.round(4).tolist(), size=(hi - lo).round(4).tolist())
    # topology
    es = mu.edge_stats(F)
    lab, nsh = mu.shells(F, len(V))
    M = C.to_manifold(V, F)
    met['topology'] = dict(**es, shells=int(nsh), manifold3d_status=str(M.status()), genus=int(M.genus()),
                           euler_characteristic=int(len(V) - es['edges'] + len(F)),
                           signed_volume_mm3=round(mu.signed_volume(V, F), 2), manifold3d_volume_mm3=round(M.volume(), 2),
                           surface_area_mm2=round(mu.area(V, F), 1),
                           watertight=es['boundary_edges'] == 0 and es['nonmanifold_edges'] == 0,
                           consistently_oriented=es['directed_duplicate_edges'] == 0)
    si_path = C.rp('work', 'cache', 'selfint_source.json')
    if not os.path.exists(si_path):
        np.savez(C.rp('work', 'cache', 'src_si.npz'), V=V, F=F)
        C.run_blender('blender_selfintersect.py', [C.rp('work', 'cache', 'src_si.npz'), si_path])
    si = C.json.load(open(si_path))
    met['topology']['self_intersections'] = dict(method='Blender BVHTree.overlap (3D-Print Toolbox method), vertex-sharing pairs ignored',
                                                 intersecting_triangle_pairs=si['intersecting_pairs'])
    met['topology']['overlapping_shells'] = 'n/a (single shell)' if nsh == 1 else 'see shells'
    # up axis evidence
    t = V[F]
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2
    nz = nrm[:, 2] / (2 * ar + 1e-30)
    zmaxf = t[:, :, 2].max(1)
    flat0 = zmaxf < 1e-6
    met['up_axis'] = dict(axis='+Z', evidence=f'{int(flat0.sum())} triangles ({ar[flat0].sum():.1f} mm2) lie exactly on z=0 facing down; cavity axis vertical; build plate transform has identity rotation')
    # front direction: area-weighted mean normal of label colours (Fildisi + Siyah on the front oval)
    fr = {}
    for i, n in enumerate(names):
        mm = col == i
        v = (nrm[mm]).sum(0)
        fr[n] = (v / (np.linalg.norm(v) + 1e-30)).round(3).tolist()
    met['front'] = dict(direction='-Y', evidence='label "YENİ YAKI" (Fildisi oval + Siyah relief letters) faces -Y and reads correctly in a view from -Y (see kaynak_on_-Y.png); figure head at +X, tail/feet at -X/-Y',
                        mean_normal_per_colour=fr)

    # ---- cavity
    rows = []
    cav_polys = {}
    for z in [0.0025, 0.05, 0.12, 0.3, 0.6, 1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 47, 48, 48.5, 49, 49.5, 49.8, 50, 50.5]:
        g = C.cs_to_shapely(M.slice(float(z)))
        cav = C.find_cavity(g)
        if cav is None:
            rows.append(dict(z=z, cavity=None))
            continue
        b = cav.bounds
        cav_polys[z] = cav
        rows.append(dict(z=z, width_x=round(b[2] - b[0], 3), depth_y=round(b[3] - b[1], 3), area=round(cav.area, 2),
                         centroid=[round(cav.centroid.x, 3), round(cav.centroid.y, 3)],
                         clearance_per_side_x=round((b[2] - b[0] - cfg['lighter']['base_long']) / 2, 3),
                         clearance_per_side_y=round((b[3] - b[1] - cfg['lighter']['base_short']) / 2, 3)))
    cents = np.array([r['centroid'] for r in rows if r.get('cavity', 1) is not None and 1 <= r['z'] <= 45])
    axis = cents.mean(0)
    ref_cav = cav_polys[25]
    # ellipse fit check: area vs ideal ellipse of same bbox
    b = ref_cav.bounds
    ell_area = np.pi * (b[2] - b[0]) / 2 * (b[3] - b[1]) / 2
    tops, full_top, frac_rows = wall_tops(M, ref_cav, 40.0, 56.0)
    open_bottom = 'width_x' in rows[0]
    met['cavity'] = dict(
        axis_xy=axis.round(4).tolist(), axis_spread_mm=float(np.abs(cents - axis).max().round(4)),
        shape=f'oval (area/bbox-ellipse ratio {ref_cav.area / ell_area:.3f}); long axis along X',
        sections=rows,
        bottom='OPEN (through-hole down to z=0, no floor)' if open_bottom else 'closed',
        floor_thickness_mm=0.0 if open_bottom else None,
        seat_z_source=0.0,
        seat_note='no floor: in the source the lighter would stand directly on the table (z=0)',
        wall_top_z_by_side=tops, full_ring_closed_up_to_z=full_top,
        wall_top_relative_to_seat=tops,
        note_wall_tops='highest z (contiguous from below) at which a probe 0.5 mm outside the cavity wall is inside material; sampled every 0.05 mm')
    # ---- underside
    zs, A, Af, P = area_curve(M, 0.0025, 4.0, 0.0125)
    zc_auto, rate = auto_zcut(zs, A, cfg['case']['growth_rate_threshold'])
    H, hlo, cell = underside_heightmap(V, F)
    sec0 = C.cs_to_shapely(M.slice(0.0025))
    met['underside'] = dict(
        min_z=float(lo[2]), vertices_at_z0=int((V[:, 2] == 0).sum()),
        faces_on_z0_area_mm2=round(float(ar[flat0].sum()), 2),
        section_area_at_z0p0025_mm2=round(sec0.area, 2),
        flat_contact_fraction=round(float(ar[flat0].sum()) / sec0.area, 4),
        downfacing_area_mm2_by_z={f'{a_}-{b_}': round(float(ar[(nz < -0.95) & (t[:, :, 2].mean(1) >= a_) & (t[:, :, 2].mean(1) < b_)].sum()), 3)
                                  for a_, b_ in [(0, 1e-6), (1e-6, 0.05), (0.05, 0.3), (0.3, 1), (1, 4), (4, 100)]},
        area_vs_z=[[round(float(z), 4), round(float(a_), 2), round(float(f_), 2)] for z, a_, f_ in zip(zs[::4], A[::4], Af[::4])],
        z_cut_auto=zc_auto,
        note='Nothing protrudes below z=0. The base is already a flat plane at z=0 (feet included); the only deviation is the rounded/scalloped knit-texture bottom edge in the lowest fraction of a mm.')
    C.save_json(os.path.join(out, 'case_metrics.json'), met)
    np.savez(C.rp('work', 'cache', 'area_curve.npz'), zs=zs, A=A, Af=Af, P=P)

    # ---- plots
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    ax[0].plot(zs, A, label='malzeme kesit alanı (kavite hariç)')
    ax[0].plot(zs, Af, label='dolu dış kontur alanı')
    ax[0].axvline(zc_auto, color='r', ls='--', label=f'z_cut auto = {zc_auto:.3f}')
    ax[0].set_xlabel('z [mm]'); ax[0].set_ylabel('alan [mm²]'); ax[0].legend(); ax[0].grid(alpha=.3)
    ax[0].set_title('Kesit alanı - z (alt 4 mm)')
    w = max(1, int(round(0.1 / (zs[1] - zs[0]))))
    ax[1].plot(zs[:-w], rate)
    ax[1].axhline(cfg['case']['growth_rate_threshold'], color='k', ls=':')
    ax[1].axvline(zc_auto, color='r', ls='--')
    ax[1].set_xlabel('z [mm]'); ax[1].set_ylabel('dA/dz [mm²/mm]'); ax[1].set_title('Alan artış hızı (0.1 mm pencere)')
    ax[1].set_ylim(-50, 400); ax[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(out, 'kaynak_alan_z.png'), dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    for z, c in zip([0.0025, 0.12, 0.3, 0.6, 1.0, 2.0, 4.0], plt.cm.viridis(np.linspace(0, 1, 7))):
        g = C.cs_to_shapely(M.slice(z))
        for p in C.parts(g):
            x, y = p.exterior.xy
            ax.plot(x, y, color=c, lw=0.8, label=f'z={z}' if p is C.parts(g)[0] else None)
            for r in p.interiors:
                x, y = r.xy
                ax.plot(x, y, color=c, lw=0.6)
    ax.plot(*axis, 'r+', ms=12)
    ax.set_aspect('equal'); ax.legend(fontsize=8); ax.grid(alpha=.3)
    ax.set_title('Alt bölge kesitleri (üstten bakış, +X sağ, +Y yukarı; ön yüz = -Y)')
    fig.tight_layout(); fig.savefig(os.path.join(out, 'kaynak_alt_kesitler.png'), dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    for z, c in zip([1, 10, 25, 40, 48], plt.cm.plasma(np.linspace(0, .85, 5))):
        g = C.cs_to_shapely(M.slice(float(z)))
        for p in C.parts(g):
            for r in [p.exterior] + list(p.interiors):
                x, y = r.xy
                ax.plot(x, y, color=c, lw=0.7)
        ax.plot([], [], color=c, label=f'z={z}')
    ax.plot(*axis, 'k+', ms=12)
    ax.set_aspect('equal'); ax.legend(fontsize=8); ax.grid(alpha=.3)
    ax.set_title(f'Kesitler: kavite {rows[10]["width_x"]} x {rows[10]["depth_y"]} mm, eksen {axis.round(3).tolist()}')
    fig.tight_layout(); fig.savefig(os.path.join(out, 'kaynak_kavite_kesitler.png'), dpi=110); plt.close(fig)

    Hm = np.where(np.isfinite(H), H, np.nan)
    fig, ax = plt.subplots(figsize=(11, 6))
    ext = [hlo[0], hlo[0] + H.shape[0] * cell, hlo[1], hlo[1] + H.shape[1] * cell]
    im = ax.imshow(Hm.T, origin='lower', extent=ext, cmap='turbo', vmin=0, vmax=1.0)
    plt.colorbar(im, ax=ax, label='en alt yüzey z [mm] (0 = tabla)')
    ax.set_title('Alt yüz yükseklik haritası (alttan görünüm değil; üstten bakış koordinatları)')
    ax.set_aspect('equal')
    fig.tight_layout(); fig.savefig(os.path.join(out, 'kaynak_alt_yukseklik.png'), dpi=110); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    fr_ = np.array(frac_rows)
    ax.plot(fr_[:, 0], fr_[:, 1])
    ax.set_xlabel('z'); ax.set_ylabel('kavite çevresinde malzeme oranı'); ax.grid(alpha=.3)
    ax.set_title('Kılıf duvarı üst kotu (0.5 mm dış halka)')
    fig.tight_layout(); fig.savefig(os.path.join(out, 'kaynak_duvar_ust.png'), dpi=110); plt.close(fig)

    if not a.no_render:
        np.savez(C.rp('work', 'cache', 'src_render.npz'), V=V.astype(np.float32), F=F.astype(np.int32), mat=col.astype(np.int32))
        cols = [C.hex_rgb(m[1][:7]) for m in mats]
        C.render_views([dict(npz=C.rp('work', 'cache', 'src_render.npz'), colors=cols)], C.SIX_VIEWS, out, 'kaynak')
    print('done in %.1fs' % (time.time() - t0))
    print(C.json.dumps({k: met[k] for k in ('counts', 'bbox', 'cavity')}, indent=1, default=C._jdef, ensure_ascii=False)[:6000])
    print('z_cut_auto', zc_auto, 'underside', {k: v for k, v in met['underside'].items() if k != 'area_vs_z'})


if __name__ == '__main__':
    main()
