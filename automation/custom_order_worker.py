#!/usr/bin/env python3
"""
Custom Order Worker (runs inside the "Custom Order" GitHub Actions workflow).

  python automation/custom_order_worker.py ORD-XXXX

1. Reads the order from Supabase (service role key).
2. Submits a Meshy.ai text-to-3D / image-to-3D task and polls until it finishes.
3. Downloads the GLB, exports STL (+3MF when possible) to work/custom/<figure_id>/.
4. Writes design_pack/custom_<order_id>.json and stores it in the design_packs table.

Order status is NOT changed here: the webhook sets "queued" and delivery_notify.py moves it
to "delivered"/"failed" based on this workflow's conclusion. Errors are written to error_message
and the script exits non-zero so the workflow run fails.

Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, MESHY_API_KEY
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "automation"))
from webhook_handler import DESIGN_PACK_TEMPLATE  # noqa: E402

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
MESHY_API_KEY = os.getenv("MESHY_API_KEY")
MESHY_BASE = "https://api.meshy.ai/openapi"
MAX_WAIT_S = int(os.getenv("MESHY_MAX_WAIT", "1500"))


def sb_headers(extra: dict | None = None) -> dict:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def get_order(order_id: str) -> dict:
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/orders", headers=sb_headers(),
                  params={"order_id": f"eq.{order_id}", "select": "*"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"Order {order_id} not found in Supabase")
    return rows[0]


def update_order(order_id: str, updates: dict) -> None:
    r = httpx.patch(f"{SUPABASE_URL}/rest/v1/orders", headers=sb_headers({"Prefer": "return=minimal"}),
                    params={"order_id": f"eq.{order_id}"}, json=updates, timeout=30)
    r.raise_for_status()


def meshy_headers() -> dict:
    return {"Authorization": f"Bearer {MESHY_API_KEY}", "Content-Type": "application/json"}


def meshy_submit(order: dict) -> tuple[str, str]:
    """Return (task_id, poll_path)."""
    if order["input_method"] == "prompt":
        path = "v2/text-to-3d"
        body = {"mode": "preview", "prompt": order["prompt"], "art_style": "realistic", "should_remesh": True}
    else:
        path = "v1/image-to-3d"
        body = {"image_url": order["image_b64"], "enable_pbr": False, "should_remesh": True}
    r = httpx.post(f"{MESHY_BASE}/{path}", headers=meshy_headers(), json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Meshy submit failed ({r.status_code}): {r.text[:300]}")
    task_id = r.json().get("result")
    if not task_id:
        raise RuntimeError(f"Meshy returned no task id: {r.text[:300]}")
    return task_id, path


def meshy_poll(task_id: str, path: str) -> str:
    start = time.time()
    while time.time() - start < MAX_WAIT_S:
        r = httpx.get(f"{MESHY_BASE}/{path}/{task_id}", headers=meshy_headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        print(f"[meshy] {task_id}: {status} {data.get('progress', '')}", flush=True)
        if status == "SUCCEEDED":
            url = (data.get("model_urls") or {}).get("glb")
            if not url:
                raise RuntimeError("Meshy task succeeded but returned no GLB url")
            return url
        if status in ("FAILED", "CANCELED", "EXPIRED"):
            raise RuntimeError(f"Meshy task {status}: {(data.get('task_error') or {}).get('message', '')}")
        time.sleep(10)
    raise TimeoutError(f"Meshy task {task_id} timed out after {MAX_WAIT_S}s")


def download_model(url: str, out_dir: Path) -> dict:
    import trimesh

    out_dir.mkdir(parents=True, exist_ok=True)
    glb = out_dir / "model.glb"
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(glb, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    files = {"glb": str(glb.relative_to(ROOT))}
    scene = trimesh.load(glb, force="scene")
    mesh = trimesh.util.concatenate(tuple(scene.dump()))
    stl = out_dir / "model.stl"
    mesh.export(stl)
    files["stl"] = str(stl.relative_to(ROOT))
    try:
        tmf = out_dir / "model.3mf"
        mesh.export(tmf)
        files["3mf"] = str(tmf.relative_to(ROOT))
    except Exception as e:  # 3MF export needs optional deps
        print(f"[model] 3MF export skipped: {e}")
    print(f"[model] {len(mesh.vertices)} vertices, watertight={mesh.is_watertight}")
    return files


def write_design_pack(order: dict, files: dict) -> Path:
    figure_id = f"custom_{order['order_id']}"
    pack = copy.deepcopy(DESIGN_PACK_TEMPLATE)
    pack["figure_id"] = figure_id
    pack["assets"]["model_3mf"] = files.get("3mf", files["stl"])
    pack["assets"]["model_glb"] = files["glb"]
    pack["geometry_overrides"]["case"] = {"plinth_default_colour": order.get("plinth_color", "Pembe")}
    pins = [int(p) for p in (order.get("pins") or "8,4,2").split(",") if p.strip().isdigit()]
    pack["geometry_overrides"]["stand"] = {"pins": pins}
    pack["geometry_overrides"]["plinth_height"] = order.get("plinth_height", "3.0")
    path = ROOT / "design_pack" / f"{figure_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")

    r = httpx.post(f"{SUPABASE_URL}/rest/v1/design_packs", headers=sb_headers({"Prefer": "return=minimal"}),
                   json={"order_id": order["id"], "figure_id": figure_id, "design_pack": pack}, timeout=30)
    if r.status_code >= 400:
        print(f"[design_pack] Supabase insert failed ({r.status_code}): {r.text[:200]}")
    return path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    order_id = sys.argv[1].strip()
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    order = get_order(order_id)
    print(f"[order] {order_id} method={order['input_method']} status={order['status']}")
    try:
        if not MESHY_API_KEY:
            raise RuntimeError("MESHY_API_KEY secret is not configured")
        task_id, path = meshy_submit(order)
        update_order(order_id, {"meshy_task_id": task_id})
        model_url = meshy_poll(task_id, path)
        update_order(order_id, {"meshy_model_url": model_url})
        files = download_model(model_url, ROOT / "work" / "custom" / f"custom_{order_id}")
        pack_path = write_design_pack(order, files)
        update_order(order_id, {"design_pack_path": str(pack_path.relative_to(ROOT)), "error_message": None})
        print(f"[done] design pack: {pack_path}")
        return 0
    except Exception as e:
        print(f"[error] {e}")
        try:
            update_order(order_id, {"error_message": str(e)[:500]})
        except Exception as e2:
            print(f"[error] could not record error: {e2}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
