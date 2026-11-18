#!/usr/bin/env python3
"""
Marketing Asset Generator

From render pipeline outputs (output/marketing/{figure_id}/) generate
platform-ready assets for Instagram, TikTok, Shopify, Email, etc.

Usage:
    python asset_generator.py --figure panter_v2 --calendar marketing/content_calendar.yaml
    python asset_generator.py --figure panter_v2 --platform instagram --output-dir output/social/panter_v2
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

from PIL import Image, ImageDraw, ImageFont, ImageFilter


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True)


def load_calendar(calendar_path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML not installed. Run: pip install pyyaml")
    with open(calendar_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_figure_marketing_dir(figure_id: str) -> Path:
    return Path(f"output/marketing/{figure_id}")


def crop_image_ffmpeg(input_path: Path, output_path: Path, aspect: str, target_size: str = None) -> bool:
    """Crop image to aspect ratio using ffmpeg."""
    aspect_map = {
        "1:1": "1",
        "9:16": "9/16",
        "4:5": "4/5",
        "16:9": "16/9",
    }
    target = aspect_map.get(aspect)
    if not target:
        return False

    if target_size:
        scale = f"scale={target_size}"
    else:
        scale = ""

    vf = f"crop=ih*{target}:ih"
    if scale:
        vf += f",{scale}"

    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vf", vf, str(output_path)]
    r = run_cmd(cmd)
    return r.returncode == 0


def crop_image_pil(input_path: Path, output_path: Path, aspect: str, target_size: tuple = None) -> bool:
    """Crop image to aspect ratio using PIL (center crop)."""
    try:
        img = Image.open(input_path)
        w, h = img.size

        aspect_map = {
            "1:1": (1, 1),
            "9:16": (9, 16),
            "4:5": (4, 5),
            "16:9": (16, 9),
        }
        aw, ah = aspect_map.get(aspect, (1, 1))

        # Calculate crop box
        target_w = min(w, int(h * aw / ah))
        target_h = min(h, int(w * ah / aw))

        left = (w - target_w) // 2
        top = (h - target_h) // 2
        right = left + target_w
        bottom = top + target_h

        cropped = img.crop((left, top, right, bottom))

        if target_size:
            cropped = cropped.resize(target_size, Image.Resampling.LANCZOS)

        cropped.save(output_path, quality=95)
        return True
    except Exception as e:
        print(f"  PIL crop failed: {e}")
        return False


def add_branding_overlay(input_path: Path, output_path: Path, logo_path: Path = None, tagline: str = None) -> bool:
    """Add logo and tagline overlay to image."""
    try:
        img = Image.open(input_path).convert("RGBA")
        w, h = img.size

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Add tagline at bottom
        if tagline:
            try:
                font_size = max(24, h // 30)
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()

            text_w = draw.textlength(tagline, font=font)
            x = (w - text_w) // 2
            y = h - font_size - 30

            # Semi-transparent background
            padding = 10
            draw.rounded_rectangle(
                [x - padding, y - padding, x + text_w + padding, y + font_size + padding],
                radius=8, fill=(0, 0, 0, 180)
            )
            draw.text((x, y), tagline, font=font, fill=(255, 255, 255, 255))

        # Add logo bottom-right
        if logo_path and logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            logo_size = min(w, h) // 8
            logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            img.paste(logo, (w - logo_size - 20, h - logo_size - 20), logo)

        result = Image.alpha_composite(img, overlay)
        result.convert("RGB").save(output_path, quality=95)
        return True
    except Exception as e:
        print(f"  Branding overlay failed: {e}")
        return False


def create_carousel(input_paths: list[Path], output_path: Path, cols: int = 1) -> bool:
    """Create carousel image (vertical stack for Instagram)."""
    try:
        images = [Image.open(p).convert("RGB") for p in input_paths]
        # Resize all to same width
        target_w = min(img.width for img in images)
        resized = []
        for img in images:
            ratio = target_w / img.width
            new_h = int(img.height * ratio)
            resized.append(img.resize((target_w, new_h), Image.Resampling.LANCZOS))

        total_h = sum(img.height for img in resized)
        carousel = Image.new("RGB", (target_w, total_h), (255, 255, 255))
        y = 0
        for img in resized:
            carousel.paste(img, (0, y))
            y += img.height

        carousel.save(output_path, quality=95)
        return True
    except Exception as e:
        print(f"  Carousel creation failed: {e}")
        return False


def generate_qr_code(data: str, output_path: Path, size: int = 512) -> bool:
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        img.save(output_path)
        return True
    except Exception as e:
        print(f"  QR generation failed: {e}")
        return False


def verify_assets(marketing_dir: Path, requirements: dict) -> dict[str, bool]:
    """Check which required assets exist."""
    results = {}
    for category, assets in requirements.items():
        for asset in assets:
            path = marketing_dir / asset
            results[asset] = path.exists()
    return results


def main():
    ap = argparse.ArgumentParser(description="Generate marketing assets from render outputs")
    ap.add_argument("--figure", required=True, help="Figure ID (e.g., panter_v2)")
    ap.add_argument("--calendar", help="Path to content_calendar.yaml")
    ap.add_argument("--platform", choices=["all", "instagram", "tiktok", "shopify", "email"], default="all")
    ap.add_argument("--output-dir", help="Output directory (default: marketing_dir/social/)")
    ap.add_argument("--verify-only", action="store_true", help="Only verify assets exist")
    ap.add_argument("--branding", action="store_true", help="Add logo/tagline overlays")
    args = ap.parse_args()

    figure_id = args.figure
    marketing_dir = get_figure_marketing_dir(figure_id)

    if not marketing_dir.exists():
        sys.exit(f"Marketing directory not found: {marketing_dir}")

    print(f"Generating assets for {figure_id}")
    print(f"Source: {marketing_dir}")

    # Load calendar for requirements
    calendar = None
    if args.calendar and Path(args.calendar).exists():
        calendar = load_calendar(Path(args.calendar))
        requirements = calendar.get("asset_requirements", {})
    else:
        requirements = {}

    if args.verify_only:
        results = verify_assets(marketing_dir, requirements)
        print("\nAsset verification:")
        for asset, exists in results.items():
            status = "✓" if exists else "✗ MISSING"
            print(f"  {status} {asset}")
        missing = sum(1 for v in results.values() if not v)
        if missing:
            print(f"\n{missing} asset(s) missing")
            sys.exit(1)
        else:
            print("\nAll assets present!")
        return

    output_dir = Path(args.output_dir) if args.output_dir else marketing_dir / "social"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nOutput: {output_dir}")

    # Social media crops
    print("\n1. Generating social media crops...")
    video_path = marketing_dir / "social" / "reels_9_16.mp4"
    if video_path.exists():
        print(f"  Video found: {video_path}")
    else:
        print(f"  ⚠ Video not found: {video_path}")

    # Generate stills for each platform
    stills_dir = marketing_dir / "stills"
    if stills_dir.exists():
        stills = list(stills_dir.glob("*.png"))
        print(f"  Found {len(stills)} still images")

    # Generate platform-specific assets
    platforms = ["instagram", "tiktok", "shopify", "email"] if args.platform == "all" else [args.platform]

    for platform in platforms:
        print(f"\n2. Generating {platform} assets...")
        platform_dir = output_dir / platform
        platform_dir.mkdir(parents=True, exist_ok=True)

        if platform == "instagram":
            # 1:1 carousel (hero + 3-4 + side + AR QR)
            hero_stills = {
                "front": "hero_front_1_1.png",
                "3-4": "hero_34_1_1.png",
                "side": "hero_side_1_1.png",
                "back": "hero_back_1_1.png",
            }
            carousel_srcs = []
            for angle, fname in hero_stills.items():
                src = marketing_dir / "social" / fname
                if src.exists():
                    dst = platform_dir / f"carousel_{angle}_1_1.jpg"
                    shutil.copy2(src, dst)
                    carousel_srcs.append(dst)
                    print(f"  ✓ {fname} -> {dst.name}")

            # Add QR as last slide
            qr_src = marketing_dir / "qr" / f"{figure_id}_qr.png"
            if qr_src.exists():
                dst = platform_dir / "carousel_qr_1_1.jpg"
                shutil.copy2(qr_src, dst)
                carousel_srcs.append(dst)

            if carousel_srcs:
                create_carousel(carousel_srcs, platform_dir / "carousel_1_1.jpg")
                print(f"  ✓ Carousel created")

            # Reels 9:16 (copy video)
            reels_src = marketing_dir / "social" / "reels_9_16.mp4"
            if reels_src.exists():
                shutil.copy2(reels_src, platform_dir / "reels_9_16.mp4")
                print(f"  ✓ Reels video copied")

            # Stories 9:16 stills
            for fname in ["hero_front_9_16.png", "hero_34_9_16.png", "qr_panter_v2.png"]:
                src = marketing_dir / "social" / fname
                if src.exists():
                    dst = platform_dir / f"story_{fname}"
                    shutil.copy2(src, dst)

        elif platform == "tiktok":
            # 9:16 video
            reels_src = marketing_dir / "social" / "reels_9_16.mp4"
            if reels_src.exists():
                shutil.copy2(reels_src, platform_dir / "tiktok_9_16.mp4")
                print(f"  ✓ TikTok video copied")

            # 9:16 still for cover
            for fname in ["hero_front_9_16.png", "hero_34_9_16.png"]:
                src = marketing_dir / "social" / fname
                if src.exists():
                    dst = platform_dir / f"cover_{fname}"
                    shutil.copy2(src, dst)

        elif platform == "shopify":
            # Hero 1:1
            for fname in ["hero_front_1_1.png", "hero_34_1_1.png", "hero_side_1_1.png"]:
                src = marketing_dir / "social" / fname
                if src.exists():
                    dst = platform_dir / fname
                    shutil.copy2(src, dst)
                    print(f"  ✓ {fname}")

            # 4:5 variants
            for fname in ["hero_front_4_5.png", "hero_34_4_5.png", "hero_side_4_5.png"]:
                src = marketing_dir / "social" / fname
                if src.exists():
                    dst = platform_dir / fname
                    shutil.copy2(src, dst)

            # AR embed code
            embed_code = f'''<model-viewer src="https://u2lighter.com/ar/{args.figure}.glb" 
    alt="u2Lighter Panter v2" 
    auto-rotate camera-controls tone-mapping="aces" exposure="1.0" 
    shadow-intensity="0.5" environment-image="neutral" ar 
    ar-modes="webxr scene-viewer quick-look" 
    ios-src="https://u2lighter.com/ar/{args.figure}.usdz"
    poster="https://u2lighter.com/social/hero_front_1_1.jpg">
</model-viewer>
<script type="module" src="https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>'''
            (platform_dir / "ar_embed.html").write_text(embed_code)
            print(f"  ✓ AR embed code generated")

        elif platform == "email":
            # Hero image + AR button
            hero_src = marketing_dir / "social" / "hero_front_1_1.png"
            if hero_src.exists():
                shutil.copy2(hero_src, platform_dir / "email_hero.jpg")

            # QR code
            qr_src = marketing_dir / "qr" / f"{figure_id}_qr.png"
            if qr_src.exists():
                shutil.copy2(qr_src, platform_dir / "email_qr.png")

            # Email HTML template
            email_html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
  <img src="cid:hero" alt="Panter v2" style="width: 100%; max-width: 600px; height: auto; border-radius: 12px; display: block;">
  <div style="text-align: center; margin: 24px 0;">
    <a href="https://u2lighter.com/ar/{args.figure}" style="display: inline-block; background: #ec4899; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 600;">🎮 View in AR</a>
  </div>
  <p style="text-align: center; color: #6b7280; font-size: 14px;">Scan QR code with iPhone camera to open in AR</p>
  <img src="cid:qr" alt="QR Code" style="max-width: 180px; border-radius: 8px; border: 1px solid #fce7f3;">
  <p style="text-align: center; color: #6b7280; font-size: 12px; margin-top: 24px;">u2Lighter — Light your style</p>
</body>
</html>'''
            (platform_dir / "email_template.html").write_text(email_html)
            print(f"  ✓ Email template generated")

    print(f"\n✓ All assets generated in {output_dir}")
    print(f"  Structure:")
    for p in sorted(output_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(output_dir)
            print(f"    {rel}")


if __name__ == "__main__":
    main()