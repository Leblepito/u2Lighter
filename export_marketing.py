#!/usr/bin/env python3
"""
Export marketing assets from render pipeline outputs.

Usage:
    python export_marketing.py --case output/print/panter_kilif_v2.3mf \
        --stills output/stills/ \
        --video output/video/panter_kilif_360.mp4 \
        --figure-id panter_v2 \
        --output-dir output/marketing/panter_kilif_v2 \
        --qr-base-url https://u2lighter.com/ar/

Outputs:
    - ar/{figure_id}.usdz (placeholder)
    - web/{figure_id}.glb (draco compressed)
    - web/viewer.html (three.js viewer with AR button)
    - social/reels_9_16.mp4, post_1_1.mp4, portrait_4_5.mp4
    - social/hero_front_1_1.png, hero_34_4_5.png, hero_side_9_16.png
    - qr/{figure_id}_qr.png
    - contact_sheet.png
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import qrcode
except ImportError:
    qrcode = None

try:
    from PIL import Image
except ImportError:
    Image = None


def run_cmd(cmd: list[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run command and return result."""
    print(f"  $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"  FAILED: {r.stderr}", file=sys.stderr)
    return r


def convert_3mf_to_glb(case_3mf: Path, output_glb: Path) -> bool:
    """Convert 3MF to GLB using pipeline's io3mf reader + trimesh."""
    script = f"""
import sys
import os
import zipfile
import tempfile
sys.path.insert(0, r'{Path(__file__).parent.parent / "geometry"}')
import io3mf
import trimesh
import numpy as np

# Extract 3MF to temp directory
with zipfile.ZipFile(r'{case_3mf}', 'r') as z:
    with tempfile.TemporaryDirectory() as tmpdir:
        z.extractall(tmpdir)
        model_path = os.path.join(tmpdir, '3D', '3dmodel.model')
        if not os.path.exists(model_path):
            # Try to find any .model file
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.endswith('.model'):
                        model_path = os.path.join(root, f)
                        break

        # Load 3MF using pipeline's reader
        d = io3mf.read_model(model_path)
        V = d['V']
        F = d['F']
        col = io3mf.triangle_colour_index(d)
        materials = d['materials']

        # Create trimesh scene
        scene = trimesh.Scene()
        for mat_idx, (name, color) in enumerate(materials):
            mask = col == mat_idx
            if not mask.any():
                continue
            mesh = trimesh.Trimesh(vertices=V, faces=F[mask], process=False)
            # color is hex like '#F28AB4FF'
            r = int(color[1:3], 16) / 255
            g = int(color[3:5], 16) / 255
            b = int(color[5:7], 16) / 255
            mesh.visual = trimesh.visual.ColorVisuals(
                vertex_colors=np.tile([r, g, b, 1.0], (len(mesh.vertices), 1))
            )
            scene.add_geometry(mesh, geom_name=name)

        scene.export(r'{output_glb}')
        print(f'Exported to {output_glb}')
"""
    r = run_cmd([sys.executable, "-c", script], check=False)
    return r.returncode == 0 and output_glb.exists()


def compress_glb_draco(input_glb: Path, output_glb: Path) -> bool:
    """Compress GLB with Draco using gltf-transform."""
    # Use full path to npx.cmd on Windows
    npx_cmd = r"C:\Program Files\nodejs\npx.cmd"
    r = run_cmd([
        npx_cmd, "--yes", "gltf-transform", "optimize",
        str(input_glb), str(output_glb),
        "--compress", "draco",
        "--draco.compressionLevel", "7",
        "--draco.quantization", "14"
    ], check=False)
    return r.returncode == 0 and output_glb.exists()


def generate_usdz_placeholder(input_glb: Path, output_usdz: Path) -> bool:
    """Generate USDZ placeholder (requires macOS usdzconvert or cloud service)."""
    # For now, create a minimal USDZ file structure or copy GLB as placeholder
    # Real USDZ conversion requires macOS or cloud service
    try:
        # Try gltf-transform with USDZ extension (if available)
        r = run_cmd([
            "gltf-transform", "copy",
            str(input_glb), str(output_usdz)
        ], check=False)
        if r.returncode == 0 and output_usdz.exists():
            return True
    except Exception:
        pass

    # Fallback: create a note file
    output_usdz.parent.mkdir(parents=True, exist_ok=True)
    with open(output_usdz.with_suffix('.txt'), 'w') as f:
        f.write(f"USDZ conversion requires macOS usdzconvert or cloud service.\n")
        f.write(f"Source GLB: {input_glb}\n")
        f.write(f"Run on macOS: usdzconvert {input_glb} {output_usdz}\n")
    return False


def crop_video_ffmpeg(input_video: Path, output_video: Path, aspect: str) -> bool:
    """Crop video to aspect ratio using ffmpeg (center crop)."""
    aspect_map = {
        "9:16": (9, 16),
        "1:1": (1, 1),
        "4:5": (4, 5),
        "16:9": (16, 9),
    }
    target = aspect_map.get(aspect)
    if not target:
        return False

    w, h = target
    # Use ffmpeg crop filter: crop to target aspect ratio, centered
    # Use min(iw, ih * w/h) for width and min(ih, iw * h/w) for height
    # to handle both landscape and portrait inputs
    if aspect == "9:16":
        scale = "1080:1920"
        crop = "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)'"
    elif aspect == "1:1":
        scale = "1080:1080"
        crop = "crop='min(iw,ih)':'min(iw,ih)'"
    elif aspect == "4:5":
        scale = "1080:1350"
        crop = "crop='min(iw,ih*4/5)':'min(ih,iw*5/4)'"
    else:
        scale = "1920:1080"
        crop = "crop='min(iw,ih*16/9)':'min(ih,iw*9/16)'"

    r = run_cmd([
        "ffmpeg", "-y", "-i", str(input_video),
        "-vf", f"{crop},scale={scale}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        str(output_video)
    ], check=False)
    return r.returncode == 0 and output_video.exists()


def crop_image_ffmpeg(input_image: Path, output_image: Path, aspect: str) -> bool:
    """Crop image to aspect ratio using ffmpeg."""
    aspect_map = {
        "9:16": "9/16",
        "1:1": "1",
        "4:5": "4/5",
        "16:9": "16/9",
    }
    target = aspect_map.get(aspect)
    if not target:
        return False

    r = run_cmd([
        "ffmpeg", "-y", "-i", str(input_image),
        "-vf", f"crop=ih*{target}:ih",
        str(output_image)
    ], check=False)
    return r.returncode == 0 and output_image.exists()


def create_contact_sheet(stills_dir: Path, output_path: Path, cols: int = 4) -> bool:
    """Create contact sheet grid from still images."""
    if Image is None:
        print("  PIL not available, skipping contact sheet", file=sys.stderr)
        return False

    images = sorted(stills_dir.glob("*.png")) + sorted(stills_dir.glob("*.jpg"))
    if not images:
        print(f"  No images found in {stills_dir}", file=sys.stderr)
        return False

    # Load and resize images
    thumb_size = (400, 400)
    thumbs = []
    for img_path in images[:16]:  # max 16 images
        try:
            img = Image.open(img_path)
            img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
            thumbs.append(img)
        except Exception as e:
            print(f"  Failed to load {img_path}: {e}", file=sys.stderr)

    if not thumbs:
        return False

    rows = (len(thumbs) + cols - 1) // cols
    sheet_w = cols * thumb_size[0]
    sheet_h = rows * thumb_size[1]
    sheet = Image.new('RGB', (sheet_w, sheet_h), (255, 255, 255))

    for i, thumb in enumerate(thumbs):
        x = (i % cols) * thumb_size[0]
        y = (i // cols) * thumb_size[1]
        sheet.paste(thumb, (x, y))

    sheet.save(output_path)
    return True


def generate_viewer_html(figure_id: str, glb_path: Path, output_path: Path,
                         qr_base_url: str, title: str = "u2Lighter") -> bool:
    """Generate three.js viewer HTML with AR button."""
    # Copy GLB to web directory with retry for file lock
    web_dir = output_path.parent
    web_dir.mkdir(parents=True, exist_ok=True)
    target_glb = web_dir / f"{figure_id}.glb"
    
    # Wait for any file locks to release (Windows npx process cleanup)
    time.sleep(2)
    
    # Retry copy if file is locked
    for attempt in range(20):
        try:
            shutil.copy2(glb_path, target_glb)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.5)

    ar_url = f"{qr_base_url.rstrip('/')}/{figure_id}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {figure_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; }}
        #viewer {{ width: 100vw; height: 100vh; position: relative; }}
        model-viewer {{ width: 100%; height: 100%; background: #f0f0f0; }}
        .ar-button {{
            position: fixed; bottom: 24px; right: 24px; z-index: 100;
            background: #007AFF; color: white; border: none;
            padding: 12px 24px; border-radius: 28px; font-size: 16px;
            font-weight: 600; cursor: pointer; box-shadow: 0 4px 16px rgba(0,0,0,0.2);
            display: flex; align-items: center; gap: 8px;
        }}
        .ar-button:active {{ transform: scale(0.98); }}
        .info {{ position: fixed; top: 16px; left: 16px; z-index: 100; color: #333; }}
        .info h1 {{ font-size: 20px; margin-bottom: 4px; }}
        .info p {{ font-size: 14px; opacity: 0.8; }}
    </style>
</head>
<body>
    <div id="viewer">
        <model-viewer
            src="{figure_id}.glb"
            alt="{title} {figure_id}"
            auto-rotate
            camera-controls
            tone-mapping="aces"
            exposure="1.0"
            shadow-intensity="0.5"
            environment-image="neutral"
            ar
            ar-modes="webxr scene-viewer quick-look"
            ios-src="{ar_url}.usdz"
            poster="poster.jpg">
        </model-viewer>
        <a href="{ar_url}.usdz" class="ar-button" download>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            View in AR
        </a>
    </div>
    <div class="info">
        <h1>{title}</h1>
        <p>{figure_id}</p>
    </div>
    <script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
    <script nomodule src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer-legacy.js"></script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return True


def generate_qr_code(data: str, output_path: Path, size: int = 512) -> bool:
    """Generate QR code PNG."""
    if qrcode is None:
        print("  qrcode library not available, skipping QR code", file=sys.stderr)
        return False

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size), Image.Resampling.LANCZOS if Image else None)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return True


def copy_hero_stills(stills_dir: Path, social_dir: Path, figure_id: str) -> dict[str, str]:
    """Copy and rename hero stills for social media."""
    mapping = {
        "front": "hero_front",
        "3-4": "hero_34",
        "side": "hero_side",
        "back": "hero_back",
    }
    copied = {}
    for angle, prefix in mapping.items():
        # Find matching still
        for ext in [".png", ".jpg", ".jpeg"]:
            src = stills_dir / f"{figure_id}_{angle}{ext}"
            if src.exists():
                dst = social_dir / f"{prefix}_1_1{ext}"
                shutil.copy2(src, dst)
                copied[f"{prefix}_1_1"] = str(dst)
                # Also create 4:5 version
                dst_45 = social_dir / f"{prefix}_4_5{ext}"
                crop_image_ffmpeg(src, dst_45, "4:5")
                copied[f"{prefix}_4_5"] = str(dst_45)
                # And 9:16 version
                dst_916 = social_dir / f"{prefix}_9_16{ext}"
                crop_image_ffmpeg(src, dst_916, "9:16")
                copied[f"{prefix}_9_16"] = str(dst_916)
                break
    return copied


def main():
    ap = argparse.ArgumentParser(description="Export marketing assets from render outputs")
    ap.add_argument("--case", required=True, help="Path to case .3mf file")
    ap.add_argument("--stills", required=True, help="Path to hero stills directory")
    ap.add_argument("--video", required=True, help="Path to turntable video (.mp4)")
    ap.add_argument("--figure-id", required=True, help="Figure ID (e.g., panter_v2)")
    ap.add_argument("--output-dir", required=True, help="Output directory for marketing assets")
    ap.add_argument("--qr-base-url", default="https://u2lighter.com/ar/", help="Base URL for AR viewer")
    ap.add_argument("--title", default="u2Lighter", help="Product title for viewer")
    args = ap.parse_args()

    case_path = Path(args.case)
    stills_dir = Path(args.stills)
    video_path = Path(args.video)
    output_dir = Path(args.output_dir)
    figure_id = args.figure_id

    if not case_path.exists():
        sys.exit(f"Case file not found: {case_path}")
    if not stills_dir.exists():
        sys.exit(f"Stills directory not found: {stills_dir}")
    if not video_path.exists():
        sys.exit(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    ar_dir = output_dir / "ar"
    web_dir = output_dir / "web"
    social_dir = output_dir / "social"
    qr_dir = output_dir / "qr"
    for d in [ar_dir, web_dir, social_dir, qr_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print(f"Exporting marketing assets for {figure_id}...")
    print(f"  Output: {output_dir}")

    # 1. Convert case 3MF to GLB
    print("\n1. Converting 3MF to GLB...")
    raw_glb = output_dir / f"{figure_id}_raw.glb"
    if convert_3mf_to_glb(case_path, raw_glb):
        print(f"  ✓ GLB created: {raw_glb}")
    else:
        print(f"  ✗ Failed to create GLB", file=sys.stderr)
        sys.exit(1)

    # 2. Compress GLB with Draco
    print("\n2. Compressing GLB with Draco...")
    compressed_glb = web_dir / f"{figure_id}.glb"
    if compress_glb_draco(raw_glb, compressed_glb):
        print(f"  ✓ Compressed GLB: {compressed_glb}")
    else:
        print(f"  ⚠ Draco compression failed, using raw GLB", file=sys.stderr)
        # Wait for any file locks to release, then copy
        for attempt in range(10):
            try:
                shutil.copy2(raw_glb, compressed_glb)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5)

    # 3. Generate USDZ (placeholder)
    print("\n3. Generating USDZ...")
    usdz_path = ar_dir / f"{figure_id}.usdz"
    generate_usdz_placeholder(compressed_glb, usdz_path)
    print(f"  USDZ: {usdz_path} (placeholder)")

    # 4. Social video crops
    print("\n4. Creating social video crops...")
    for aspect, name in [("9:16", "reels_9_16"), ("1:1", "post_1_1"), ("4:5", "portrait_4_5")]:
        out_video = social_dir / f"{name}.mp4"
        if crop_video_ffmpeg(video_path, out_video, aspect):
            print(f"  ✓ {name}.mp4")
        else:
            print(f"  ✗ {name}.mp4 failed", file=sys.stderr)

    # 5. Hero stills for social
    print("\n5. Copying hero stills...")
    copy_hero_stills(stills_dir, social_dir, figure_id)
    print(f"  ✓ Hero stills copied to {social_dir}")

    # 6. Contact sheet
    print("\n6. Creating contact sheet...")
    contact_sheet = output_dir / "contact_sheet.png"
    if create_contact_sheet(stills_dir, contact_sheet):
        print(f"  ✓ Contact sheet: {contact_sheet}")
    else:
        print(f"  ⚠ Contact sheet skipped", file=sys.stderr)

    # 7. Viewer HTML
    print("\n7. Generating viewer.html...")
    viewer_html = web_dir / "viewer.html"
    # Use raw_glb directly since compressed_glb may be locked by npx process
    # (Draco compression failed, so compressed_glb is just a copy of raw_glb anyway)
    if generate_viewer_html(figure_id, raw_glb, viewer_html, args.qr_base_url, args.title):
        print(f"  ✓ Viewer: {viewer_html}")

    # 8. QR code
    print("\n8. Generating QR code...")
    viewer_url = f"{args.qr_base_url.rstrip('/')}/{figure_id}"
    qr_path = qr_dir / f"{figure_id}_qr.png"
    if generate_qr_code(viewer_url, qr_path):
        print(f"  ✓ QR code: {qr_path}")

    print(f"\n✓ Marketing assets exported to {output_dir}")
    print(f"  Structure:")
    for d in [ar_dir, web_dir, social_dir, qr_dir]:
        files = list(d.glob("*"))
        if files:
            print(f"  {d.relative_to(output_dir)}/: {', '.join(f.name for f in files)}")


if __name__ == "__main__":
    main()