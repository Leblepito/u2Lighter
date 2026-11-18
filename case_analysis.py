"""Geometry analysis of the lighter case (numpy only, mm units).

detect_cavity(verts, tris, mat, materials) finds the vertical lighter sleeve:
  1. top-down height map (max z per 0.25 mm cell, sampled at vertices, edge
     midpoints and centroids of every triangle; 3x3 closing fills sampling gaps)
  2. "deep" cells = height below 40 % of the model height; connected
     components that do not touch the grid border are candidate wells
  3. the largest well -> PCA gives the axis (centroid) and major-axis direction
  4. exact inner wall: radial min distance of vertices in the mid-height band,
     per 2-degree sector, in the well's local frame
  5. seat height = median height-map value inside the well (0 = open to ground)
  6. front direction = side of the minor axis where the ivory label (Fildisi)
     lies; figure side = side of the major axis holding most non-label mass
     (pink + yellow) -> the spark wheel goes there, the gas button opposite.
"""
import json
import math
from collections import deque

import numpy as np

CELL = 0.25


def _heightmap(verts, tris, cell=CELL):
    tv = verts[tris]                                   # (M,3,3)
    pts = [verts, tv.mean(1),
           0.5 * (tv[:, 0] + tv[:, 1]), 0.5 * (tv[:, 1] + tv[:, 2]),
           0.5 * (tv[:, 2] + tv[:, 0])]
    # large triangles (e.g. a flat plinth / cavity floor) need dense sampling,
    # otherwise their interior cells look empty ("open to ground")
    e = np.max(np.linalg.norm(tv - np.roll(tv, 1, axis=1), axis=2), axis=1)
    big = np.nonzero(e > 1.5 * cell)[0]
    if len(big):
        for k in np.unique(np.ceil(e[big] / (0.5 * cell)).astype(int)):
            sel = big[np.ceil(e[big] / (0.5 * cell)).astype(int) == k]
            k = min(int(k), 400)
            ii, jj = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
            m = (ii + jj) <= k
            a, b = ii[m] / k, jj[m] / k
            w = np.stack([1 - a - b, a, b], 1)                 # (S,3) barycentric
            for c0 in range(0, len(sel), max(1, 2000000 // len(w))):
                chunk = tv[sel[c0:c0 + max(1, 2000000 // len(w))]]
                pts.append(np.einsum("sk,tkd->tsd", w, chunk).reshape(-1, 3))
    P = np.concatenate(pts)
    mn = verts[:, :2].min(0) - 2 * cell
    ij = np.floor((P[:, :2] - mn) / cell).astype(np.int64)
    W, H = ij.max(0) + 3
    hm = np.full((W, H), -1.0)
    np.maximum.at(hm, (ij[:, 0], ij[:, 1]), P[:, 2])
    return hm, mn


def _components(mask):
    W, H = mask.shape
    lab = np.zeros(mask.shape, np.int32)
    comps = []
    for i0, j0 in zip(*np.nonzero(mask)):
        if lab[i0, j0]:
            continue
        n = len(comps) + 1
        q = deque([(i0, j0)])
        lab[i0, j0] = n
        cells, border = [], False
        while q:
            i, j = q.popleft()
            cells.append((i, j))
            if i == 0 or j == 0 or i == W - 1 or j == H - 1:
                border = True
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if 0 <= a < W and 0 <= b < H and mask[a, b] and not lab[a, b]:
                    lab[a, b] = n
                    q.append((a, b))
        comps.append((np.array(cells), border))
    return comps


def detect_cavity(verts, tris, mat, materials):
    zmax = float(verts[:, 2].max())
    zmin = float(verts[:, 2].min())
    hm, mn = _heightmap(verts, tris)
    # sampling pinholes in the surface only create tiny wells; the largest
    # enclosed well is the sleeve
    deep = (hm < zmin + 0.4 * (zmax - zmin))
    comps = [(c, b) for c, b in _components(deep) if not b]
    if not comps:
        raise RuntimeError("cavity detection failed: no enclosed deep well")
    cells, _ = max(comps, key=lambda cb: len(cb[0]))
    xy = mn + (cells + 0.5) * CELL
    c0 = xy.mean(0)
    cov = np.cov((xy - c0).T)
    w, vec = np.linalg.eigh(cov)
    major = vec[:, 1] / np.linalg.norm(vec[:, 1])
    minor = np.array([-major[1], major[0]])
    floor_vals = hm[cells[:, 0], cells[:, 1]]
    open_frac = float(np.mean(floor_vals < -0.5))
    seat = float(np.median(np.where(floor_vals < -0.5, zmin, floor_vals)))
    if open_frac > 0.5:
        seat = zmin

    # exact inner wall in the mid-height band
    band = (verts[:, 2] > seat + 5.0) & (verts[:, 2] < seat + 0.75 * (zmax - seat))
    rel = verts[band, :2] - c0
    u, v = rel @ major, rel @ minor
    r = np.hypot(u, v)
    near = r < 25.0
    ang = np.degrees(np.arctan2(v[near], u[near])) % 360
    rr = r[near]
    sector = (ang // 2).astype(int)
    rmin = np.full(180, np.inf)
    np.minimum.at(rmin, sector, rr)
    # refine centre so that opposite walls are symmetric
    def _ext(deg):
        k = int((deg % 360) // 2)
        return float(np.min(rmin[[k - 1, k, (k + 1) % 180]]))
    a_pos, a_neg = _ext(0), _ext(180)
    b_pos, b_neg = _ext(90), _ext(270)
    c1 = c0 + major * (a_pos - a_neg) / 2 + minor * (b_pos - b_neg) / 2
    inner_major = a_pos + a_neg
    inner_minor = b_pos + b_neg

    # orientation from colours
    names = [m[0].lower() for m in materials]
    def _idx(*keys):
        for k in keys:
            for i, n in enumerate(names):
                if k in n:
                    return i
        return None
    i_label = _idx("fildisi", "ivory", "label")
    tri_c = verts[tris].mean(1)
    if i_label is not None and np.any(mat == i_label):
        lab = tri_c[mat == i_label, :2].mean(0) - c1
        front = minor if lab @ minor > 0 else -minor
    else:
        front = -minor
    fig_mask = np.ones(len(mat), bool) if i_label is None else (mat != i_label)
    fig = tri_c[fig_mask, :2]
    # mass outside the cavity footprint only
    d = fig - c1
    outside = (np.abs(d @ major) > inner_major / 2 + 1) | (np.abs(d @ minor) > inner_minor / 2 + 1)
    side = float(np.mean((d[outside] @ major)))
    wheel_dir = major if side > 0 else -major
    head_hint = None
    i_eye = _idx("sari", "yellow")
    if i_eye is not None and np.any(mat == i_eye):
        head_hint = float((tri_c[mat == i_eye, :2].mean(0) - c1) @ wheel_dir)

    # front-face rim height (top of wall right in front / behind the cavity)
    def _rim(direction):
        p = c1 + direction * (inner_minor / 2 + 1.0)
        sel = np.linalg.norm(verts[:, :2] - p, axis=1) < 1.0
        return float(verts[sel, 2].max()) if np.any(sel) else None

    res = {
        "axis_xy_mm": [float(c1[0]), float(c1[1])],
        "major_dir": [float(wheel_dir[0]), float(wheel_dir[1])],
        "front_dir": [float(front[0]), float(front[1])],
        "seat_z_mm": seat,
        "cavity_open_to_ground_fraction": open_frac,
        "inner_major_mm": inner_major,
        "inner_minor_mm": inner_minor,
        "rim_front_z_mm": _rim(front),
        "rim_back_z_mm": _rim(-front),
        "figure_mass_along_major_mm": side,
        "eyes_along_wheel_dir_mm": head_hint,
        "model_zmin_mm": zmin, "model_zmax_mm": zmax,
        "bbox_min_mm": verts.min(0).tolist(), "bbox_max_mm": verts.max(0).tolist(),
        "major_angle_deg": float(math.degrees(math.atan2(wheel_dir[1], wheel_dir[0]))),
        "well_cells": int(len(cells)),
        "_rmin_sectors": rmin.tolist(),
    }
    return res


def clearance_check(cav, a=12.0, b=6.0, margin=0.0):
    """Min gap (mm) between an a x b semi-axis ellipse and the inner wall."""
    rmin = np.array(cav["_rmin_sectors"])
    gaps = []
    for k in range(180):
        t = math.radians(k * 2 + 1)
        # ellipse radius at polar angle t
        re = a * b / math.sqrt((b * math.cos(t)) ** 2 + (a * math.sin(t)) ** 2)
        if np.isfinite(rmin[k]):
            gaps.append(rmin[k] - re)
    return float(min(gaps)), float(np.median(gaps))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from mf3 import load_3mf
    r = load_3mf(sys.argv[1])
    cav = detect_cavity(r["verts"], r["tris"], r["mat"], r["materials"])
    print(json.dumps({k: v for k, v in cav.items() if not k.startswith("_")}, indent=1))
    print("clearance min/median (mm):", clearance_check(cav))
