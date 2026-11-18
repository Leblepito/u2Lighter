"""3MF reader/writer for the Bambu-style single-object, basematerials + per-triangle colour dialect.

Reader: regex over chunks of the model XML (never builds a DOM), caches numpy arrays to .npz.
Writer: core-spec 3MF (basematerials, per-triangle pid/p1) plus Bambu `paint_color`
attribute (mmu_segmentation) when present, and copies Metadata/*.config files.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from collections import Counter

import numpy as np

VERT_RE = re.compile(rb'<vertex x="([-0-9.eE+]+)" y="([-0-9.eE+]+)" z="([-0-9.eE+]+)"\s*/>')
TRI_RE = re.compile(rb'<triangle\s([^>]*?)/>')
ATTR_RE = re.compile(rb'(\w+)="([^"]*)"')
BASE_RE = re.compile(rb'<base name="([^"]*)" displaycolor="([^"]*)"\s*/>')


def _chunks(path, size=1 << 24):
    """Yield byte chunks that always end on a '>' boundary (tags never split)."""
    with open(path, 'rb') as f:
        tail = b''
        while True:
            buf = f.read(size)
            if not buf:
                if tail:
                    yield tail
                return
            buf = tail + buf
            cut = buf.rfind(b'>') + 1
            yield buf[:cut]
            tail = buf[cut:]


def read_model(path):
    """Parse 3dmodel.model. Returns dict with V (n,3) float64, F (m,3) int64,
    pid (m,) int32 (-1 = inherit), p1 (m,) int32 (-1 = inherit), paint (m,) object(str or ''),
    materials list[(name, colour)], object attrs, build transform, attr stats."""
    xs, fs = [], []
    pids, p1s, paints = [], [], []
    attr_sets = Counter()
    header = b''
    footer = b''
    first = True
    for chunk in _chunks(path):
        if first:
            idx = chunk.find(b'<vertices>')
            header = chunk[: idx if idx >= 0 else 4096]
            first = False
        vm = VERT_RE.findall(chunk)
        if vm:
            xs.append(np.array(vm, dtype=np.float64))
        for m in TRI_RE.finditer(chunk):
            a = dict(ATTR_RE.findall(m.group(1)))
            attr_sets[tuple(sorted(a.keys()))] += 1
            fs.append((int(a[b'v1']), int(a[b'v2']), int(a[b'v3'])))
            pids.append(int(a[b'pid']) if b'pid' in a else -1)
            p1s.append(int(a[b'p1']) if b'p1' in a else -1)
            paints.append(a.get(b'paint_color', b'').decode())
        footer = chunk[-4096:]
    V = np.concatenate(xs, 0) if xs else np.zeros((0, 3))
    F = np.array(fs, dtype=np.int64)
    mats = [(n.decode('utf-8'), c.decode()) for n, c in BASE_RE.findall(header)]
    obj = re.search(rb'<object ([^>]*)>', header)
    obj_attrs = {k.decode(): v.decode('utf-8') for k, v in ATTR_RE.findall(obj.group(1))} if obj else {}
    tr = re.search(rb'<item [^>]*transform="([^"]*)"', footer)
    transform = [float(t) for t in tr.group(1).split()] if tr else None
    title = re.search(rb'<metadata name="Title">([^<]*)</metadata>', header)
    app = re.search(rb'<metadata name="Application">([^<]*)</metadata>', header)
    return dict(V=V, F=F, pid=np.array(pids, np.int32), p1=np.array(p1s, np.int32),
                paint=np.array(paints, dtype=object), materials=mats, obj_attrs=obj_attrs,
                transform=transform,
                title=title.group(1).decode('utf-8') if title else '',
                application=app.group(1).decode('utf-8') if app else '',
                attr_sets={'|'.join(k.decode() for k in ks): v for ks, v in attr_sets.items()})


def load_cached(model_path, cache_path):
    if os.path.exists(cache_path) and os.path.getmtime(cache_path) > os.path.getmtime(model_path):
        d = np.load(cache_path, allow_pickle=True)
        return {k: (d[k].item() if d[k].dtype == object and d[k].shape == () else d[k]) for k in d.files}
    d = read_model(model_path)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    np.savez(cache_path, **{k: (np.array(v, dtype=object) if not isinstance(v, np.ndarray) else v)
                            for k, v in d.items()})
    return load_cached(model_path, cache_path)


# --------------------------------------------------------------------------- colour helpers
# Bambu/Prusa mmu_segmentation: leaf triangle state s encoded as hex nibble(s):
# s=1 -> "4", s=2 -> "8", s>=3 -> nibble 0xC followed by nibble (s-3)  e.g. 3->"0C", 4->"1C".
# Strings are reversed-nibble trees; a single-state (unsplit) triangle is exactly the codes above.
PAINT_FOR_STATE = {1: '4', 2: '8', 3: '0C', 4: '1C', 5: '2C', 6: '3C', 7: '4C', 8: '5C'}
STATE_FOR_PAINT = {v: k for k, v in PAINT_FOR_STATE.items()}


def triangle_colour_index(d):
    """Effective 0-based basematerial index per triangle (what a core-spec reader sees)."""
    default = int(d['obj_attrs'].get('pindex', 0)) if isinstance(d['obj_attrs'], dict) else 0
    p1 = d['p1'].astype(np.int64)
    return np.where(p1 >= 0, p1, default)


def paint_state(d):
    """Bambu paint state per triangle: 0 = unpainted (object extruder), k = extruder k, -1 = split/mixed."""
    out = np.zeros(len(d['paint']), np.int32)
    for i, s in enumerate(d['paint']):
        if s:
            out[i] = STATE_FOR_PAINT.get(s, -1)
    return out


# --------------------------------------------------------------------------- writers
def write_3mf(out_path, objects, materials, metadata_dir=None, title='', application='',
              model_settings_xml=None, plate_transform_xy=(128.0, 128.0)):
    """objects: list of dicts {name, V (n,3), F (m,3), mat (m,) int base index or None,
    paint (m,) list[str] or None, transform (12 floats) or None}.
    materials: list[(name, '#RRGGBBAA')]. Objects get ids 1..n, one basematerials group id n+1."""
    buf = io.StringIO()
    w = buf.write
    w('<?xml version="1.0" encoding="UTF-8"?>\n')
    w('<model unit="millimeter" xml:lang="tr-TR" '
      'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n')
    if application:
        w(f'<metadata name="Application">{application}</metadata>\n')
    if title:
        w(f'<metadata name="Title">{_esc(title)}</metadata>\n')
    mid = len(objects) + 1  # source dialect: object id 1, basematerials id 2
    w(f'<resources>\n<basematerials id="{mid}">')
    for n, c in materials:
        w(f'<base name="{_esc(n)}" displaycolor="{c}"/>')
    w('</basematerials>\n')
    for k, o in enumerate(objects):
        oid = k + 1
        w(f'<object id="{oid}" type="model" name="{_esc(o["name"])}" pid="{mid}" pindex="{int(o.get('pindex', 0))}"><mesh><vertices>')
        V = np.asarray(o['V'])
        lines = ['<vertex x="%.6f" y="%.6f" z="%.6f"/>' % tuple(v) for v in V]
        w(''.join(lines))
        w('</vertices><triangles>')
        F = np.asarray(o['F'])
        mat = o.get('mat')
        paint = o.get('paint')
        parts = []
        for i, (a, b, c) in enumerate(F):
            s = f'<triangle v1="{a}" v2="{b}" v3="{c}"'
            if mat is not None:
                s += f' pid="{mid}" p1="{int(mat[i])}"'
            if paint is not None and paint[i]:
                s += f' paint_color="{paint[i]}"'
            parts.append(s + '/>')
        w(''.join(parts))
        w('</triangles></mesh></object>\n')
    w('</resources>\n<build>')
    for k, o in enumerate(objects):
        t = o.get('transform') or [1, 0, 0, 0, 1, 0, 0, 0, 1, plate_transform_xy[0], plate_transform_xy[1], 0]
        w(f'<item objectid="{k + 1}" transform="{" ".join(_fmt(x) for x in t)}" printable="1"/>')
    w('</build>\n</model>\n')
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                   '<Default Extension="config" ContentType="application/octet-stream"/></Types>')
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
                   'Target="/3D/3dmodel.model"/></Relationships>')
        z.writestr('3D/3dmodel.model', buf.getvalue().encode('utf-8'))
        if metadata_dir and os.path.isdir(metadata_dir):
            for fn in sorted(os.listdir(metadata_dir)):
                if fn == 'model_settings.config' and model_settings_xml is not None:
                    continue
                z.write(os.path.join(metadata_dir, fn), 'Metadata/' + fn)
        if model_settings_xml is not None:
            z.writestr('Metadata/model_settings.config', model_settings_xml)


def model_settings_for(objects_names, plates, extruder=1):
    """Bambu model_settings.config: objects_names list[str]; plates list[list[object_index]] (0-based)."""
    s = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>']
    for k, n in enumerate(objects_names):
        s.append(f'<object id="{k + 1}"><metadata key="name" value="{_esc(n)}"/>'
                 f'<metadata key="extruder" value="{extruder}"/></object>')
    for pi, objs in enumerate(plates):
        s.append(f'<plate><metadata key="plater_id" value="{pi + 1}"/>')
        for oi in objs:
            s.append(f'<model_instance><metadata key="object_id" value="{oi + 1}"/>'
                     f'<metadata key="instance_id" value="0"/></model_instance>')
        s.append('</plate>')
    s.append('</config>')
    return ''.join(s)


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def _fmt(x):
    return ('%.6f' % x).rstrip('0').rstrip('.') if isinstance(x, float) else str(x)


def write_stl_binary(path, V, F):
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    tri = V[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    rec = np.zeros(len(F), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    rec['n'] = n
    rec['v'] = tri
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'binary STL'.ljust(80, b' '))
        f.write(np.uint32(len(F)).tobytes())
        f.write(rec.tobytes())
