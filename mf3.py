"""Streaming 3MF loader (no Blender dependency, needs numpy).

load_3mf(path) accepts either an unzipped `.model` XML file or a `.3mf` zip
archive and returns a dict:

    verts      float64 (N,3)  in millimetres, build-item transform applied
    tris       int32   (M,3)
    mat        int16   (M,)   index into `materials`
    materials  list of (name, (r,g,b,a))   from the first <basematerials>
    title      str

Colour resolution per triangle (3MF core + materials extension):
  triangle pid/p1  ->  else object pid/pindex  ->  else Bambu/Prusa
  `paint_color` simple codes ("4"->0, "8"->1, "0C"->2, "1C"->3, ...)  ->  0.
Objects built from <components> (Bambu "3D/Objects/*.model") are resolved
recursively with their transforms.  The XML is parsed with
ElementTree.iterparse and elements are cleared as we go, so memory stays at
the size of the numeric arrays, not the XML tree.
"""
import io
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from array import array

import numpy as np

PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_transform(s):
    if not s:
        return None
    v = [float(x) for x in s.split()]
    if len(v) != 12:
        return None
    m = np.eye(4)
    # 3MF: m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32 (row vectors)
    m[:3, :3] = np.array(v[:9]).reshape(3, 3).T
    m[:3, 3] = v[9:12]
    return m


def _hex_rgba(s):
    s = s.lstrip("#")
    if len(s) == 6:
        s += "FF"
    r, g, b, a = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))
    return (r, g, b, a)


_PAINT_SIMPLE = {"4": 1, "8": 2}


def _decode_paint(code):
    """Decode a *uniform* Bambu/Prusa mmu paint code to an extruder (1-based)."""
    if code in _PAINT_SIMPLE:
        return _PAINT_SIMPLE[code]
    m = re.fullmatch(r"([0-9A-F])C", code)
    if m:
        return int(m.group(1), 16) + 3
    return None


def _parse_model_stream(fp, models, materials, path_key):
    """Parse one .model stream. Fills models[(path_key, id)] and materials."""
    title = ""
    obj = None
    vbuf = tbuf = mbuf = None
    in_base = None
    for ev, el in ET.iterparse(fp, events=("start", "end")):
        tag = _local(el.tag)
        if ev == "start":
            if tag == "object":
                obj = {"id": el.get("id"), "pid": el.get("pid"),
                       "pindex": int(el.get("pindex", "0") or 0),
                       "components": [], "name": el.get("name", "")}
                vbuf, tbuf, mbuf = array("d"), array("i"), array("h")
            elif tag == "basematerials":
                in_base = el.get("id")
                materials.setdefault(in_base, [])
            continue
        # end events
        if tag == "vertex":
            vbuf.append(float(el.get("x")))
            vbuf.append(float(el.get("y")))
            vbuf.append(float(el.get("z")))
        elif tag == "triangle":
            tbuf.append(int(el.get("v1")))
            tbuf.append(int(el.get("v2")))
            tbuf.append(int(el.get("v3")))
            p1 = el.get("p1")
            if p1 is not None:
                mbuf.append(int(p1))
            else:
                pc = el.get("paint_color")
                d = _decode_paint(pc) if pc else None
                mbuf.append(d - 1 if d else -1)
        elif tag == "base" and in_base is not None:
            materials[in_base].append(
                (el.get("name", ""), _hex_rgba(el.get("displaycolor", "#808080"))))
        elif tag == "basematerials":
            in_base = None
        elif tag == "component":
            path = el.get("{%s}path" % PROD_NS) or el.get("path") or path_key
            obj["components"].append((path.lstrip("/"), el.get("objectid"),
                                      _parse_transform(el.get("transform"))))
        elif tag == "object":
            if len(vbuf):
                v = np.frombuffer(vbuf, dtype=np.float64).reshape(-1, 3).copy()
                t = np.frombuffer(tbuf, dtype=np.int32).reshape(-1, 3).copy()
                mt = np.frombuffer(mbuf, dtype=np.int16).copy()
                mt[mt < 0] = obj["pindex"]
                obj["mesh"] = (v, t, mt)
            models[(path_key, obj["id"])] = obj
            obj = None
            vbuf = tbuf = mbuf = None
        elif tag == "metadata" and el.get("name") == "Title":
            title = el.text or ""
        elif tag == "item":
            models.setdefault("__items__", []).append(
                (path_key, el.get("objectid"), _parse_transform(el.get("transform"))))
        if tag in ("vertex", "triangle", "base", "component", "item", "object"):
            el.clear()
    return title


def _collect(models, key, xf, out):
    obj = models.get(key)
    if obj is None:
        raise KeyError("3MF object not found: %r" % (key,))
    if "mesh" in obj:
        v, t, m = obj["mesh"]
        if xf is not None:
            v = v @ xf[:3, :3].T + xf[:3, 3]
        out.append((v, t, m))
    for path, oid, cxf in obj["components"]:
        m2 = xf if cxf is None else (cxf if xf is None else xf @ cxf)
        _collect(models, (path, oid), m2, out)


def load_3mf(path, apply_build_transform=False, verbose=True):
    t0 = time.time()
    models, materials = {}, {}
    path = os.fspath(path)
    title = ""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".model")]
            # main model last so component targets are already parsed
            main = None
            rels = "_rels/.rels"
            if rels in z.namelist():
                m = re.search(rb'Target="/?([^"]+\.model)"', z.read(rels))
                if m:
                    main = m.group(1).decode()
            if main is None:
                main = "3D/3dmodel.model" if "3D/3dmodel.model" in names else names[0]
            for n in sorted(names, key=lambda n: n == main):
                with z.open(n) as fp:
                    tt = _parse_model_stream(fp, models, materials, n)
                    if n == main:
                        title = tt
            main_key = main
    else:
        main_key = "3D/3dmodel.model"
        with open(path, "rb") as fp:
            title = _parse_model_stream(fp, models, materials, main_key)
    items = [it for it in models.get("__items__", []) if it[0] == main_key]
    parts = []
    for pk, oid, xf in items:
        _collect(models, (pk, oid), xf if apply_build_transform else None, parts)
    if not parts:
        raise RuntimeError("no mesh found in %s" % path)
    off = 0
    V, T, M = [], [], []
    for v, t, m in parts:
        V.append(v)
        T.append(t + off)
        M.append(m)
        off += len(v)
    mats = next(iter(materials.values()), [])
    res = {"verts": np.concatenate(V), "tris": np.concatenate(T).astype(np.int32),
           "mat": np.concatenate(M), "materials": mats, "title": title}
    if verbose:
        print("[mf3] %s: %d verts, %d tris, %d materials, %.1fs" % (
            os.path.basename(path), len(res["verts"]), len(res["tris"]),
            len(mats), time.time() - t0))
    return res


if __name__ == "__main__":
    r = load_3mf(sys.argv[1])
    v = r["verts"]
    print("bbox min", v.min(0), "max", v.max(0))
    print("materials", r["materials"])
    print("tri counts per material", np.bincount(r["mat"]))
