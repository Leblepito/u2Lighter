"""Shared helpers: config, paths, source loading, manifold <-> numpy, cross-sections, raster renders."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import manifold3d as m3
import shapely
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(HERE)
sys.path.insert(0, HERE)
import io3mf  # noqa: E402

BLENDER = os.environ.get('BLENDER_EXE', r'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe')

PALETTE = {  # name -> (hex, paint_color code)
    'Pembe': ('#F28AB4', '4'), 'Siyah': ('#242225', '8'), 'Fildisi': ('#F4DFC4', '0C'), 'Sari': ('#F8C32B', '1C')}


def load_config(path=None):
    path = path or os.path.join(HERE, 'config.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def rp(*parts):
    """Path relative to project root."""
    return os.path.join(ROOT, *parts)


def load_source(cfg):
    d = io3mf.load_cached(rp(cfg['source_model']), rp('work', 'cache', 'source.npz'))
    d['mats'] = [tuple(x) for x in d['materials']]
    return d


def hex_rgb(h):
    h = h.lstrip('#')
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def to_manifold(V, F, face_id=None):
    mesh = m3.Mesh64(vert_properties=np.array(V, np.float64, order="C", copy=True),
                     tri_verts=np.array(F, np.uint64, order="C", copy=True),
                     face_id=None if face_id is None else np.array(face_id, np.uint64, order="C", copy=True))
    M = m3.Manifold(mesh)
    return M


def from_manifold(M):
    mesh = M.to_mesh64()
    V = np.asarray(mesh.vert_properties)[:, :3].astype(np.float64)
    F = np.asarray(mesh.tri_verts).astype(np.int64)
    fid = np.asarray(mesh.face_id).astype(np.int64) if mesh.face_id is not None and len(mesh.face_id) else None
    run_index = np.asarray(mesh.run_index).astype(np.int64)
    run_oid = np.asarray(mesh.run_original_id).astype(np.int64)
    # per-triangle original id
    tri_oid = np.zeros(len(F), np.int64)
    for k in range(len(run_oid)):
        tri_oid[run_index[k] // 3: run_index[k + 1] // 3] = run_oid[k]
    return V, F, fid, tri_oid


def cs_to_shapely(cs):
    """CrossSection -> shapely geometry using even-odd (XOR) of contours (valid for nested, non-crossing contours)."""
    polys = [np.asarray(p) for p in cs.to_polygons()]
    geom = Polygon()
    for p in sorted(polys, key=lambda p: -abs(_area(p))):
        if len(p) < 3:
            continue
        q = Polygon(p)
        if not q.is_valid:
            q = q.buffer(0)
        geom = geom.symmetric_difference(q)
    return geom


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def parts(g):
    if g.is_empty:
        return []
    return list(g.geoms) if hasattr(g, 'geoms') else [g]


def fill_holes(g):
    return unary_union([Polygon(p.exterior) for p in parts(g)])


def find_cavity(geom, min_area=100.0, axis_hint=None):
    """Return the largest interior ring (hole) polygon with area > min_area (the lighter cavity)."""
    best = None
    for p in parts(geom):
        for r in p.interiors:
            h = Polygon(r)
            if h.area < min_area:
                continue
            if axis_hint is not None and not h.contains(Point(axis_hint)):
                continue
            if best is None or h.area > best.area:
                best = h
    return best


def run_blender(script, args, timeout=1800):
    cmd = [BLENDER, '-b', '--factory-startup', '--python', os.path.join(HERE, script), '--'] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        raise RuntimeError(f'blender failed ({r.returncode}):\n{out[-3000:]}')
    return out


def render_views(meshes, views, scene_dir, name, res=(1000, 1000)):
    """meshes: list of dicts for blender_render.py; views: list of (tag, dir, up). Writes PNGs into scene_dir."""
    os.makedirs(scene_dir, exist_ok=True)
    vs = []
    for v in views:
        tag, dvec, up = v[:3]
        e = dict(name=tag, dir=dvec, up=up, out=os.path.join(scene_dir, f'{name}_{tag}.png'))
        if len(v) > 3 and v[3]:
            e.update(v[3])
        vs.append(e)
    sp = os.path.join(scene_dir, f'_scene_{name}.json')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(dict(meshes=meshes, views=vs, res=list(res)), f)
    run_blender('blender_render.py', ['--scene', sp])
    os.remove(sp)
    return [v['out'] for v in vs]


SIX_VIEWS = [('on_-Y', [0, -1, 0], [0, 0, 1]), ('arka_+Y', [0, 1, 0], [0, 0, 1]),
             ('sol_-X', [-1, 0, 0], [0, 0, 1]), ('sag_+X', [1, 0, 0], [0, 0, 1]),
             ('alt', [0, 0, -1], [0, -1, 0]), ('izo', [-0.6, -1, 0.7], [0, 0, 1])]


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=_jdef)


def _jdef(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return round(float(o), 4)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))
