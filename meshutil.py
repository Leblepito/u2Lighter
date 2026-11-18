"""Mesh helpers: topology stats, shells, robust planar slicing (shapely)."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union


def edge_stats(F):
    """Undirected edge use counts + directed duplicate check (orientation consistency)."""
    F = np.asarray(F, np.int64)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    n = int(F.max()) + 1
    ue = np.sort(e, axis=1)
    key_u = ue[:, 0] * n + ue[:, 1]
    _, cnt = np.unique(key_u, return_counts=True)
    key_d = e[:, 0] * n + e[:, 1]
    _, dcnt = np.unique(key_d, return_counts=True)
    degenerate = int(np.sum((F[:, 0] == F[:, 1]) | (F[:, 1] == F[:, 2]) | (F[:, 0] == F[:, 2])))
    return dict(edges=int(len(cnt)), boundary_edges=int(np.sum(cnt == 1)),
                nonmanifold_edges=int(np.sum(cnt > 2)), manifold_edges=int(np.sum(cnt == 2)),
                directed_duplicate_edges=int(np.sum(dcnt > 1)), degenerate_index_faces=degenerate)


def shells(F, nverts):
    """Connected components by shared vertices. Returns label per face, n."""
    F = np.asarray(F, np.int64)
    r = np.concatenate([F[:, 0], F[:, 1]])
    c = np.concatenate([F[:, 1], F[:, 2]])
    g = sp.coo_matrix((np.ones(len(r)), (r, c)), shape=(nverts, nverts))
    n, lab = connected_components(g, directed=False)
    flab = lab[F[:, 0]]
    u, inv = np.unique(flab, return_inverse=True)
    return inv, len(u)


def signed_volume(V, F):
    t = V[F]
    return float(np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)


def area(V, F):
    t = V[F]
    return float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2)


def slice_segments(V, F, z):
    """Segments (k,2,2) of the z-plane intersection, oriented so material is on the left
    (for outward-oriented closed shells, CCW outer loops)."""
    t = V[F]
    d = t[:, :, 2] - z
    d = np.where(np.abs(d) < 1e-9, 1e-9, d)  # nudge vertices on plane
    s = d > 0
    m = (s.sum(1) == 1) | (s.sum(1) == 2)
    t, d, s = t[m], d[m], s[m]
    segs = []
    for tri, dd, ss in zip(t, d, s):
        pts = []
        for i in range(3):
            j = (i + 1) % 3
            if ss[i] != ss[j]:
                a = dd[i] / (dd[i] - dd[j])
                pts.append(tri[i, :2] + a * (tri[j, :2] - tri[i, :2]))
        segs.append(pts)
    segs = np.array(segs)
    if len(segs) == 0:
        return np.zeros((0, 2, 2))
    # orient: normal of tri projected; material is on the side opposite the normal
    tt = t
    nrm = np.cross(tt[:, 1] - tt[:, 0], tt[:, 2] - tt[:, 0])[:, :2]
    dirv = segs[:, 1] - segs[:, 0]
    # left normal of segment = (-dy, dx); material on left means outward normal points right
    right = np.stack([dirv[:, 1], -dirv[:, 0]], 1)
    flip = np.einsum('ij,ij->i', right, nrm) < 0
    segs[flip] = segs[flip][:, ::-1]
    return segs


def chain_loops(segs, tol=1e-6):
    """Chain oriented segments into closed loops (list of (k,2) arrays)."""
    if len(segs) == 0:
        return []
    q = np.round(segs / tol).astype(np.int64)
    start = {}
    for i, (a, b) in enumerate(q):
        start.setdefault((a[0], a[1]), []).append(i)
    used = np.zeros(len(segs), bool)
    loops = []
    for i0 in range(len(segs)):
        if used[i0]:
            continue
        loop = [segs[i0][0]]
        i = i0
        while True:
            used[i] = True
            b = q[i][1]
            loop.append(segs[i][1])
            nxt = [j for j in start.get((b[0], b[1]), []) if not used[j]]
            if not nxt:
                break
            i = nxt[0]
        if len(loop) >= 4:
            loops.append(np.array(loop))
    return loops


def section(V, F, z, shell_labels=None):
    """Material cross-section at height z as a shapely (Multi)Polygon: union over shells,
    each shell evaluated with signed-area (orientation) nesting."""
    if shell_labels is None:
        groups = [np.arange(len(F))]
    else:
        groups = [np.nonzero(shell_labels == k)[0] for k in np.unique(shell_labels)]
    polys = []
    for g in groups:
        segs = slice_segments(V, F[g], z)
        if len(segs) == 0:
            continue
        loops = chain_loops(segs)
        pos, neg = [], []
        for L in loops:
            p = Polygon(L)
            if not p.is_valid:
                p = p.buffer(0)
            a = shapely.area(Polygon(L).exterior) if False else _signed_area(L)
            (pos if a > 0 else neg).append(p)
        if not pos:
            continue
        P = unary_union(pos)
        if neg:
            P = P.difference(unary_union(neg))
        polys.append(P)
    if not polys:
        return Polygon()
    return unary_union(polys)


def _signed_area(L):
    x, y = L[:, 0], L[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def fill_holes(geom):
    if geom.is_empty:
        return geom
    gs = geom.geoms if hasattr(geom, 'geoms') else [geom]
    return unary_union([Polygon(g.exterior) for g in gs])
