"""Headless Blender diagnostic renderer (Workbench, orthographic).

Usage:
  blender -b --factory-startup --python blender_render.py -- --scene scene.json

scene.json = {"meshes": [{"npz": path (V,F,mat) | "stl": path, "colors": [[r,g,b],...] (per mat idx),
                          "color": [r,g,b] (single), "matrix": 4x4 list (optional)}],
              "views": [{"name": "front", "dir": [0,-1,0], "up": [0,0,1], "out": "x.png",
                         "scale": ortho_scale (optional)}],
              "res": [w,h], "xray": false, "cavity": true}
"dir" = direction FROM the object TO the camera.
"""
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


def srgb_to_lin(c):
    return [(x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


def build_mesh(name, V, F, mat=None, colors=None):
    me = bpy.data.meshes.new(name)
    V = np.asarray(V, np.float32)
    F = np.asarray(F, np.int32)
    me.vertices.add(len(V))
    me.vertices.foreach_set('co', V.ravel())
    me.loops.add(F.size)
    me.loops.foreach_set('vertex_index', F.ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set('loop_start', np.arange(0, F.size, 3, dtype=np.int32))
    me.update(calc_edges=True)
    me.validate(verbose=False)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    cols = colors or [[0.8, 0.8, 0.8]]
    for i, c in enumerate(cols):
        m = bpy.data.materials.new(f'{name}_m{i}')
        m.diffuse_color = (*srgb_to_lin(c), 1.0)
        me.materials.append(m)
    if mat is not None and len(cols) > 1:
        me.polygons.foreach_set('material_index', np.asarray(mat, np.int32))
    for p in me.polygons:
        p.use_smooth = False
    return ob


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    import os
    scene_path = os.path.abspath(argv[argv.index('--scene') + 1])
    base = os.path.dirname(scene_path)
    cfg = json.load(open(scene_path, encoding='utf-8'))
    # all relative paths in the scene file are relative to the scene file's directory
    for m in cfg['meshes']:
        for k in ('npz', 'stl'):
            if k in m and not os.path.isabs(m[k]):
                m[k] = os.path.join(base, m[k])
    for v in cfg['views']:
        if not os.path.isabs(v['out']):
            v['out'] = os.path.join(base, v['out'])
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    allpts = []
    for k, m in enumerate(cfg['meshes']):
        if 'npz' in m:
            d = np.load(m['npz'])
            V, F = d['V'], d['F']
            mat = d['mat'] if 'mat' in d.files else None
        else:
            raw = np.fromfile(m['stl'], dtype=np.uint8)
            n = int(np.frombuffer(raw[80:84].tobytes(), np.uint32)[0])
            rec = np.frombuffer(raw[84:84 + n * 50].tobytes(),
                                dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
            V = rec['v'].reshape(-1, 3)
            F = np.arange(len(V)).reshape(-1, 3)
            mat = None
        if 'matrix' in m:
            M = np.array(m['matrix'])
            V = (np.c_[V, np.ones(len(V))] @ M.T)[:, :3]
        colors = m.get('colors') or [m.get('color', [0.75, 0.75, 0.78])]
        build_mesh(f'm{k}', V, F, mat, colors)
        allpts.append(np.asarray(V)[:: max(1, len(V) // 20000)])
    P = np.concatenate(allpts)
    lo, hi = P.min(0), P.max(0)
    ctr = Vector(((lo + hi) / 2).tolist())
    diag = float(np.linalg.norm(hi - lo))

    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_cavity = cfg.get('cavity', True)
    sh.cavity_type = 'BOTH'
    sh.show_xray = cfg.get('xray', False)
    sh.show_object_outline = True
    sh.show_shadows = False
    sc.display.render_aa = '8'
    res = cfg.get('res', [1200, 900])
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new('w') if sc.world is None else sc.world
    sc.world.color = (0.92, 0.92, 0.92)

    cam_data = bpy.data.cameras.new('cam')
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new('cam', cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam_data.clip_start = 0.01
    cam_data.clip_end = diag * 10
    for v in cfg['views']:
        dvec = Vector(v['dir']).normalized()
        up = Vector(v.get('up', [0, 0, 1]))
        target = Vector(v['target']) if 'target' in v else ctr
        cam.location = target + dvec * diag * 2
        z = dvec
        x = up.cross(z).normalized()
        y = z.cross(x)
        R = Matrix((x, y, z)).transposed()
        cam.matrix_world = Matrix.Translation(cam.location) @ R.to_4x4()
        if 'scale' in v:
            cam_data.ortho_scale = v['scale']
        else:
            pts = np.array([[x.dot(Vector(p)), y.dot(Vector(p))] for p in P[:: max(1, len(P) // 5000)]])
            ext = pts.max(0) - pts.min(0)
            aspect = res[0] / res[1]
            cam_data.ortho_scale = max(ext[0], ext[1] * aspect) * 1.08
        sc.render.filepath = v['out']
        bpy.ops.render.render(write_still=True)
        print('wrote', v['out'])


main()
