#!/usr/bin/env python3
"""
Custom Order Webhook Handler

Receives form submissions from custom_order_form.html, calls Meshy.ai API
to generate 3D model, creates design_pack, triggers GitHub Actions pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration
MESHY_API_URL = "https://api.meshy.ai/v1"
MESHY_API_KEY = os.getenv("MESHY_API_KEY")  # Set in environment
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")    # For repository_dispatch
GITHUB_REPO = os.getenv("GITHUB_REPO", "Leblepito/u2Lighter")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # For HMAC verification

# Design pack template
DESIGN_PACK_TEMPLATE = {
    "figure_id": "",
    "source": "meshy",
    "assets": {
        "model_3mf": "",
        "textures": [],
        "reference_images": []
    },
    "geometry_overrides": {},
    "render_overrides": {},
    "marketing": {
        "hero_angles": ["front", "3-4", "side", "back"],
        "lifestyle_prompts": [
            "modern desk setup with mechanical keyboard and coffee",
            "bedside nightstand with warm lighting and book",
            "gift box with tissue paper and ribbon",
            "outdoor patio table with plants and sunglasses"
        ],
        "social_crops": ["1:1", "9:16", "4:5"],
        "ar_enabled": True,
        "qr_base_url": "https://u2lighter.com/ar/",
        "branding": {
            "logo_path": "branding/logo.svg",
            "tagline": "Light your style",
            "colors": {
                "primary": "#F28AB4",
                "secondary": "#1A1A2E",
                "accent": "#FFD700"
            }
        }
    }
}


@dataclass
class Order:
    order_id: str
    customer_email: str
    input_method: str
    prompt: Optional[str]
    image_b64: Optional[str]
    ref_images_b64: list
    style: str
    plinth_color: str
    pins: str
    plinth_height: str
    notes: str
    status: str = "pending"
    created_at: str = ""
    design_pack_path: Optional[str] = None
    meshy_task_id: Optional[str] = None
    meshy_model_url: Optional[str] = None
    github_run_id: Optional[int] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


async def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC signature from webhook."""
    if not WEBHOOK_SECRET:
        return True  # Skip verification if not configured
    import hmac
    expected = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def call_meshy_text_to_3d(prompt: str) -> str:
    """Submit text-to-3D task to Meshy.ai, return task_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MESHY_API_URL}/text-to-3d",
            headers={"Authorization": f"Bearer {MESHY_API_KEY}", "Content-Type": "application/json"},
            json={"prompt": prompt, "mode": "preview", "art_style": "realistic"}
        )
        resp.raise_for_status()
        return resp.json()["task_id"]


async def call_meshy_image_to_3d(image_b64: str) -> str:
    """Submit image-to-3D task to Meshy.ai, return task_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MESHY_API_URL}/image-to-3d",
            headers={"Authorization": f"Bearer {MESHY_API_KEY}", "Content-Type": "application/json"},
            json={"image": image_b64, "mode": "preview", "art_style": "realistic"}
        )
        resp.raise_for_status()
        return resp.json()["task_id"]


async def poll_meshy_task(task_id: str, max_wait: int = 300) -> Optional[str]:
    """Poll Meshy task until complete, return model URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        start = time.time()
        while time.time() - start < max_wait:
            resp = await client.get(
                f"{MESHY_API_URL}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {MESHY_API_KEY}"}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "succeeded":
                return data.get("model_url")  # URL to download .glb/.obj
            elif data.get("status") == "failed":
                raise RuntimeError(f"Meshy task failed: {data.get('error', 'unknown')}")
            await asyncio.sleep(10)
        raise TimeoutError(f"Meshy task {task_id} timed out after {max_wait}s")


async def download_and_convert_model(model_url: str, order_id: str) -> Path:
    """Download model from Meshy, convert to 3MF, save to work/3mf/."""
    import zipfile
    import tempfile
    import trimesh

    project_root = Path(__file__).parent.parent
    work_3mf = project_root / "work" / "3mf"
    work_3mf.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(model_url)
        resp.raise_for_status()
        content = resp.content

    # Save to temp and load with trimesh
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as tmp:
        tmp.write(await client.get(model_url).content)
        tmp_path = tmp.name

    try:
        scene = trimesh.load(tmp_path, force="scene")
        # Export as OBJ then convert using pipeline's io3mf
        obj_path = project_root / "work" / "3mf" / "3D" / "3dmodel.model"
        obj_path.parent.mkdir(parents=True, exist_ok=True)

        # Simple export - in production use proper 3MF writer
        mesh = trimesh.util.concatenate(tuple(scene.geometry.values()))
        mesh.export(obj_path)

        # Create minimal 3MF structure (pipeline expects this layout)
        metadata_dir = project_root / "work" / "3mf" / "Metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        return obj_path

    finally:
        os.unlink(tmp_path)


def create_design_pack(order: Order, model_path: Path) -> Path:
    """Create design_pack JSON for the order."""
    project_root = Path(__file__).parent.parent
    design_pack_dir = project_root / "design_pack"
    design_pack_dir.mkdir(parents=True, exist_ok=True)

    pack = DESIGN_PACK_TEMPLATE.copy()
    pack["figure_id"] = f"custom_{order.order_id}"
    pack["assets"]["model_3mf"] = str(model_path.relative_to(project_root))

    # Apply custom overrides
    pack["geometry_overrides"]["case"] = {
        "plinth_default_colour": order.plinth_color,
    }
    pack["geometry_overrides"]["stand"] = {
        "tiers": [{"name": "alt", "pins": int(order.pins.split(",")[0])}]
        # Simplified - in reality parse full pins config
    }

    pack_path = design_pack_dir / f"custom_{order.order_id}.json"
    with open(pack_path, "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=2, ensure_ascii=False)

    return pack_path


async def trigger_github_actions(design_pack_path: Path, figure_id: str) -> Optional[int]:
    """Trigger GitHub Actions workflow via repository_dispatch."""
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set, skipping workflow trigger")
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.everest-preview+json",
                "Content-Type": "application/json"
            },
            json={
                "event_type": "custom_order",
                "client_payload": {
                    "figure_id": figure_id,
                    "design_pack": str(design_pack_path)
                }
            }
        )
        if resp.status_code == 204:
            # Can't get run_id from dispatch directly
            # In production, poll workflow runs or use workflow_run webhook
            return None
        resp.raise_for_status()
        return None


async def save_order_to_supabase(order: Order) -> None:
    """Save order to Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase not configured, skipping DB save")
        return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/orders",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json=asdict(order)
        )
        resp.raise_for_status()


async def process_order(order_data: dict) -> Order:
    """Main order processing pipeline."""
    order = Order(
        order_id=order_data.get("order_id", f"ORD-{uuid.uuid4().hex[:8].upper()}"),
        customer_email=order_data["email"],
        input_method=order_data.get("inputMethod", "image"),
        prompt=order_data.get("prompt"),
        image_b64=order_data.get("imageFile"),
        ref_images_b64=order_data.get("refFiles", []),
        style=order_data.get("style", "panter"),
        plinth_color=order_data.get("plinthColor", "Pembe"),
        pins=order_data.get("pins", "8,4,2"),
        plinth_height=order_data.get("plinthHeight", "3.0"),
        notes=order_data.get("notes", ""),
        status="processing",
        created_at=datetime.utcnow().isoformat()
    )

    await save_order_to_supabase(order)

    try:
        # Step 1: Generate 3D model via Meshy
        if order.input_method == "prompt" and order.prompt:
            task_id = await call_meshy_text_to_3d(order.prompt)
        elif order.input_method == "image" and order.image_b64:
            task_id = await call_meshy_image_to_3d(order.image_b64)
        else:
            raise ValueError("No valid input provided")

        order.meshy_task_id = task_id
        await save_order_to_supabase(order)

        model_url = await poll_meshy_task(task_id)
        order.meshy_model_url = model_url
        await save_order_to_supabase(order)

        # Step 2: Download and convert to 3MF
        model_path = await download_and_convert_model(model_url, order.order_id)

        # Step 3: Create design pack
        design_pack_path = create_design_pack(order, model_path)
        order.design_pack_path = str(design_pack_path)
        await save_order_to_supabase(order)

        # Step 4: Trigger GitHub Actions
        figure_id = f"custom_{order.order_id}"
        run_id = await trigger_github_actions(design_pack_path, figure_id)
        order.github_run_id = run_id
        await save_order_to_supabase(order)

        order.status = "queued"
        await save_order_to_supabase(order)

        return order

    except Exception as e:
        order.status = "failed"
        order.error_message = str(e)
        await save_order_to_supabase(order)
        raise


# HTTP handler for serverless/ASGI
async def handle_request(request_body: bytes, headers: dict) -> dict:
    """Handle incoming webhook request."""
    # Verify signature
    sig = headers.get("x-webhook-signature", "")
    if not await verify_webhook_signature(request_body, sig):
        return {"statusCode": 401, "body": "Invalid signature"}

    try:
        order_data = json.loads(request_body)
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Invalid JSON"}

    # Validate required fields
    if not order_data.get("email") or "@" not in order_data.get("email", ""):
        return {"statusCode": 400, "body": "Valid email required"}

    if not order_data.get("inputMethod") or order_data.get("inputMethod") not in ("image", "prompt"):
        return {"statusCode": 400, "body": "inputMethod must be 'image' or 'prompt'"}

    try:
        order = await process_order(order_data)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "order_id": order.order_id,
                "status": order.status,
                "message": "Order queued for production"
            })
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


# CLI entry point for testing
async def main():
    if len(sys.argv) < 2:
        print("Usage: python webhook_handler.py <order_json_file>")
        sys.exit(1)

    with open(sys.argv[1], "r") as f:
        order_data = json.load(f)

    order = await process_order(order_data)
    print(json.dumps(asdict(order), indent=2))


if __name__ == "__main__":
    asyncio.run(main())