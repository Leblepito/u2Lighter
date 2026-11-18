#!/usr/bin/env python3
"""
UGC Pipeline - Watch lifestyle_inputs folder, auto-compose branded assets

Watches work/lifestyle_inputs/ for customer photos, automatically creates
branded stills/videos for social media reposting.

Usage:
    python ugc_pipeline.py --watch
    python ugc_pipeline.py --process work/lifestyle_inputs/photo.jpg --figure panter_v2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

try:
    import yaml
except ImportError:
    yaml = None


class UGCHandler(FileSystemEventHandler):
    def __init__(self, figure_id: str, marketing_dir: Path, output_dir: Path, branding: dict):
        self.figure_id = figure_id
        self.marketing_dir = marketing_dir
        self.output_dir = output_dir
        self.branding = branding
        self.processed = set()

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(('.jpg', '.jpeg', '.png', '.heic', '.webp')):
            # Debounce: wait for file to finish writing
            time.sleep(1)
            self.process_file(Path(event.src_path))

    def process_file(self, input_path: Path):
        if input_path in self.processed:
            return
        self.processed.add(input_path)

        print(f"[UGC] Processing: {input_path.name}")
        try:
            output_dir = self.output_dir / datetime.now().strftime("%Y%m%d")
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate branded versions
            self.create_branded_still(input_path, output_dir)
            self.create_reel_cover(input_path, output_dir)

            # Log metadata
            meta = {
                "source_file": input_path.name,
                "processed_at": datetime.utcnow().isoformat(),
                "figure_id": self.figure_id,
                "output_dir": str(output_dir),
            }
            meta_path = output_dir / f"{input_path.stem}_meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            print(f"[UGC] ✓ Processed {input_path.name} -> {output_dir}")
        except Exception as e:
            print(f"[UGC] ✗ Failed {input_path.name}: {e}")

    def create_branded_still(self, input_path: Path, output_dir: Path):
        """Create branded 1:1 and 4:5 versions."""
        img = Image.open(input_path).convert("RGBA")

        # 1:1 square (Instagram post)
        square = self.crop_to_aspect(img, (1, 1))
        square = self.add_branding(square)
        square.save(output_dir / f"ugc_{input_path.stem}_1_1.jpg", quality=95)

        # 4:5 portrait (Instagram portrait)
        portrait = self.crop_to_aspect(img, (4, 5))
        portrait = self.add_branding(portrait)
        portrait.save(output_dir / f"ugc_{input_path.stem}_4_5.jpg", quality=95)

        # 9:16 story
        story = self.crop_to_aspect(img, (9, 16))
        story = self.add_branding(story)
        story.save(output_dir / f"ugc_{input_path.stem}_9_16.jpg", quality=95)

    def create_reel_cover(self, input_path: Path, output_dir: Path):
        """Create 9:16 cover image for Reel."""
        img = Image.open(input_path).convert("RGBA")
        cover = self.crop_to_aspect(img, (9, 16))
        cover = self.add_branding(cover, include_cta=True)
        cover.save(output_dir / f"ugc_{input_path.stem}_reel_cover.jpg", quality=95)

    def crop_to_aspect(self, img: Image.Image, aspect: tuple[int, int]) -> Image.Image:
        """Center crop to target aspect ratio."""
        w, h = img.size
        aw, ah = aspect

        target_w = min(w, int(h * aw / ah))
        target_h = min(h, int(w * ah / aw))

        left = (w - target_w) // 2
        top = (h - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))

    def add_branding(self, img: Image.Image, include_cta: bool = False) -> Image.Image:
        """Add logo, tagline, and optional CTA."""
        img = img.convert("RGBA")
        w, h = img.size

        # Create overlay
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Logo bottom-right
        if self.branding.get("logo_path"):
            logo_path = Path(self.branding["logo_path"])
            if logo_path.exists():
                logo = Image.open(logo_path).convert("RGBA")
                logo_size = min(w, h) // 8
                logo = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
                img.paste(logo, (w - logo_size - 20, h - logo_size - 20), logo)

        # Tagline bottom-center
        tagline = self.branding.get("tagline", "Light your style")
        try:
            font_size = max(20, h // 35)
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()

        text_w = draw.textlength(tagline, font=font)
        x = (w - text_w) // 2
        y = h - font_size - 40

        # Background
        padding = 12
        draw.rounded_rectangle(
            [x - padding, y - padding, x + text_w + padding, y + font_size + padding],
            radius=10, fill=(0, 0, 0, 180)
        )
        draw.text((x, y), tagline, font=font, fill=(255, 255, 255, 255))

        # CTA for Reels
        if include_cta:
            cta = "Tap for AR 👆"
            try:
                cta_font = ImageFont.truetype("arial.ttf", max(18, h // 40))
            except:
                cta_font = ImageFont.load_default()
            cta_w = draw.textlength(cta, font=cta_font)
            cta_x = (w - cta_w) // 2
            cta_y = y - font_size - 50
            draw.rounded_rectangle(
                [cta_x - 10, cta_y - 5, cta_x + cta_w + 10, cta_y + font.getbbox(cta)[3] + 5],
                radius=8, fill=self.branding.get("colors", {}).get("primary", "#ec4899") + "CC"
            )
            draw.text((cta_x, cta_y), cta, font=cta_font, fill=(255, 255, 255, 255))

        return Image.alpha_composite(img, overlay).convert("RGB")


def process_single(input_path: Path, figure_id: str, marketing_dir: Path, output_dir: Path, branding: dict):
    """Process a single file without watcher."""
    handler = UGCHandler(figure_id, marketing_dir, output_dir, branding)
    handler.process_file(input_path)


def watch_folder(input_dir: Path, figure_id: str, marketing_dir: Path, output_dir: Path, branding: dict):
    """Watch folder for new files."""
    handler = UGCHandler(figure_id, marketing_dir, output_dir, branding)
    observer = Observer()
    observer.schedule(handler, str(input_dir), recursive=False)
    observer.start()
    print(f"[UGC] Watching {input_dir} for new images...")
    print(f"[UGC] Output: {output_dir}")
    print("[UGC] Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def main():
    ap = argparse.ArgumentParser(description="UGC Pipeline - Auto-brand customer photos")
    ap.add_argument("--watch", action="store_true", help="Watch folder for new files")
    ap.add_argument("--process", help="Process single file")
    ap.add_argument("--input-dir", default="work/lifestyle_inputs", help="Input folder to watch")
    ap.add_argument("--figure", required=True, help="Figure ID")
    ap.add_argument("--marketing-dir", default="output/marketing", help="Marketing assets root")
    ap.add_argument("--output-dir", default="output/marketing/ugc", help="Output directory")
    ap.add_argument("--branding", help="Branding config JSON")
    args = ap.parse_args()

    figure_id = args.figure
    marketing_dir = Path(args.marketing_dir) / figure_id
    output_dir = Path(args.output_dir) / figure_id
    input_dir = Path(args.input_dir)

    # Load branding
    branding = {
        "logo_path": "branding/logo.svg",
        "tagline": "Light your style",
        "colors": {
            "primary": "#ec4899",
            "secondary": "#1a1a2e",
            "accent": "#f8c32b"
        }
    }
    if args.branding and Path(args.branding).exists():
        with open(args.branding, "r", encoding="utf-8") as f:
            branding.update(json.load(f))

    if args.process:
        input_path = Path(args.process)
        if not input_path.exists():
            sys.exit(f"File not found: {input_path}")
        process_single(input_path, figure_id, marketing_dir, output_dir, branding)

    elif args.watch:
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        watch_folder(input_dir, figure_id, marketing_dir, output_dir, branding)

    else:
        ap.print_help()


if __name__ == "__main__":
    main()