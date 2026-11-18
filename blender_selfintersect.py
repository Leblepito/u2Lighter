"""Self-intersection check with Blender's BVHTree (same method as the 3D-Print Toolbox).

Usage: blender -b --factory-startup --python blender_selfintersect.py -- in.npz out.json
in.npz must contain V (n,3) and F (m,3). Pairs of triangles that share a vertex are ignored
(adjacent triangles touch by construction).
"""
import json
import os
import sys

import numpy as np
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = os.path.abspath(argv[0]), os.path.abspath(argv[1])
d = np.load(src)
V = d['V'].astype(np.float64)
F = d['F'].astype(np.int64)
tree = BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True, epsilon=0.0)
pairs = tree.overlap(tree)
bad = []
for a, b in pairs:
    if a >= b:
        continue
    if set(F[a].tolist()) & set(F[b].tolist()):
        continue
    bad.append((a, b))
faces = sorted({i for p in bad for i in p})
cent = V[F[faces]].mean(1) if faces else np.zeros((0, 3))
res = dict(raw_overlap_pairs=len(pairs), intersecting_pairs=len(bad), intersecting_faces=len(faces),
           bbox_of_intersections=[cent.min(0).tolist(), cent.max(0).tolist()] if faces else None,
           z_hist=np.histogram(cent[:, 2], bins=[0, 1, 3, 5, 10, 20, 30, 40, 50, 60, 70])[0].tolist() if faces else [],
           sample_pairs=bad[:20])
json.dump(res, open(out, 'w'), indent=1)
np.save(out.replace('.json', '_faces.npy'), np.array(faces, np.int64))
print('SELFINTERSECT', json.dumps({k: res[k] for k in ('raw_overlap_pairs', 'intersecting_pairs', 'intersecting_faces')}))
