#!/usr/bin/env python3
"""
A/B Test Framework for Render Variants

Generates render variant configs, tracks performance, feeds back to render_overrides.

Usage:
    python ab_test_framework.py --create-config --figure panter_v2 --variants 4
    python ab_test_framework.py --log-results --figure panter_v2 --results results.csv
    python ab_test_framework.py --recommend --figure panter_v2
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def load_calendar(calendar_path: Path) -> dict:
    with open(calendar_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# Base render args from design_pack
BASE_RENDER_ARGS = {
    "start_phi": -30.0,
    "direction": -1,
    "profile": "label",
    "lens": 100.0,
    "elev": 9.0,
    "light_scale": 0.25,
    "margin": 0.05,
    "seconds": 9.0,
    "samples": 160,
    "noise": 0.02,
    "res": "1440x1920",
    "pct": 100,
    "no_lighter": False,
}

# Variant axes for A/B testing
VARIANT_AXES = {
    "start_phi": [-45, -30, -15, 0],  # Camera angle relative to label
    "lens": [85, 100, 120],  # Focal length
    "light_scale": [0.2, 0.25, 0.3],  # Exposure
    "elev": [5, 9, 15],  # Camera pitch
    "profile": ["label", "constant"],  # Speed profile
}


def generate_variant_configs(figure_id: str, num_variants: int = 4, calendar_path: str = None) -> list[dict]:
    """Generate render variant configurations for A/B testing."""
    import itertools
    import random

    # Generate all combinations
    keys = list(VARIANT_AXES.keys())
    values = list(VARIANT_AXES.values())
    all_combos = list(itertools.product(*values))

    # Randomly sample
    random.seed(42)  # Reproducible
    selected = random.sample(all_combos, min(num_variants, len(all_combos)))

    variants = []
    for i, combo in enumerate(selected):
        variant_args = BASE_RENDER_ARGS.copy()
        for key, value in zip(keys, combo):
            variant_args[key] = value

        variant = {
            "variant_id": f"{figure_id}_ab{i+1:02d}",
            "figure_id": figure_id,
            "render_args": variant_args,
            "meta": {
                "created_at": datetime.utcnow().isoformat(),
                "test_type": "render_variant",
                "axes_tested": dict(zip(keys, combo)),
            },
            "tracking": {
                "utm_source": "ab_test",
                "utm_medium": "social",
                "utm_campaign": f"{figure_id}_ab{i+1:02d}",
                "utm_content": f"variant_{i+1}",
            }
        }
        variants.append(variant)

    return variants


def save_variant_configs(variants: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save individual configs for CI rendering
    for v in variants:
        config_path = output_dir / f"{v['variant_id']}_render_args.json"
        save_json(config_path, {
            "figure_id": v["figure_id"],
            "render_args": v["render_args"],
            "tracking": v["tracking"],
            "meta": v["meta"]
        })

    # Save master config
    master_path = output_dir / "ab_test_config.json"
    save_json(master_path, {
        "test_name": f"render_ab_test_{datetime.utcnow().strftime('%Y%m%d')}",
        "created_at": datetime.utcnow().isoformat(),
        "variants": variants
    })

    print(f"Generated {len(variants)} variant configs in {output_dir}")


def generate_creative_specs(variants: list[dict], output_path: Path) -> None:
    """Generate Meta/TikTok creative specs CSV for ad upload."""
    rows = []
    for v in variants:
        vid = v["variant_id"]
        args = v["render_args"]
        tracking = v["tracking"]

        rows.append({
            "variant_id": vid,
            "creative_name": f"u2Lighter_{vid}",
            "format": "VIDEO",
            "video_file": f"output/marketing/{vid}/social/reels_9_16.mp4",
            "primary_text": f"Custom 3D printed lighter sleeve — variant {vid.split('_')[-1]}",
            "headline": "Design Your Own Sleeve",
            "description": "Upload a photo → get a 3D printed sleeve in 48h",
            "cta": "SHOP_NOW",
            "destination_url": f"https://shop.u2lighter.com/?utm_source=fb&utm_medium=social&utm_campaign={tracking['utm_campaign']}&utm_content={tracking['utm_content']}",
            "start_phi": args["start_phi"],
            "lens": args["lens"],
            "light_scale": args["light_scale"],
            "elev": args["elev"],
        })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Creative specs saved to {output_path}")


def log_results(results_path: Path, figure_id: str) -> dict:
    """Load results CSV and compute stats."""
    results = {}
    with open(results_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid = row["variant_id"]
            results[vid] = {
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "spend": float(row.get("spend", 0)),
                "conversions": int(row.get("conversions", 0)),
                "revenue": float(row.get("revenue", 0)),
            }

    # Compute metrics
    for vid, data in results.items():
        imp = data["impressions"]
        clk = data["clicks"]
        sp = data["spend"]
        conv = data["conversions"]
        rev = data["revenue"]

        data["ctr"] = (clk / imp * 100) if imp > 0 else 0
        data["cpc"] = (sp / clk) if clk > 0 else 0
        data["cpa"] = (sp / conv) if conv > 0 else 0
        data["roas"] = (rev / sp) if sp > 0 else 0
        data["cvr"] = (conv / clk * 100) if clk > 0 else 0

    return results


def recommend_winner(results: dict) -> dict:
    """Recommend winning variant based on ROAS > CTR > CVR priority."""
    if not results:
        return {"winner": None, "reason": "No results"}

    # Filter: min 100 impressions, min $10 spend
    valid = {k: v for k, v in results.items() if v["impressions"] >= 100 and v["spend"] >= 10}

    if not valid:
        return {"winner": None, "reason": "No variants meet minimum thresholds"}

    # Sort by ROAS desc, then CTR desc, then CVR desc
    sorted_variants = sorted(
        valid.items(),
        key=lambda x: (x[1]["roas"], x[1]["ctr"], x[1]["cvr"]),
        reverse=True
    )

    winner_id, winner_data = sorted_variants[0]
    return {
        "winner": winner_id,
        "metrics": winner_data,
        "reason": f"Highest ROAS ({winner_data['roas']:.2f}x), CTR {winner_data['ctr']:.2f}%"
    }


def update_render_overrides(figure_id: str, winner: dict, design_pack_path: Path) -> bool:
    """Update design_pack render_overrides with winning variant."""
    try:
        with open(design_pack_path, "r", encoding="utf-8") as f:
            pack = yaml.safe_load(f)

        # Extract winning render args (they're stored in the variant config)
        # In production, load from variant config
        winning_args = winner.get("render_args", {})

        pack.setdefault("render_overrides", {}).update(winning_args)

        with open(design_pack_path, "w", encoding="utf-8") as f:
            yaml.dump(pack, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"Updated {design_pack_path} with winning variant {winner['winner']}")
        return True
    except Exception as e:
        print(f"Failed to update design_pack: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="A/B Test Framework for render variants")
    ap.add_argument("--create-config", action="store_true", help="Generate variant configs")
    ap.add_argument("--figure", required=True, help="Figure ID")
    ap.add_argument("--variants", type=int, default=4, help="Number of variants to generate")
    ap.add_argument("--calendar", help="Path to content_calendar.yaml")
    ap.add_argument("--output-dir", default="marketing/ab_tests", help="Output directory")
    ap.add_argument("--log-results", help="Path to results CSV")
    ap.add_argument("--recommend", action="store_true", help="Recommend winner from results")
    ap.add_argument("--apply-winner", action="store_true", help="Update design_pack with winner")
    args = ap.parse_args()

    figure_id = args.figure
    output_dir = Path(args.output_dir) / figure_id

    if args.create_config:
        variants = generate_variant_configs(figure_id, args.variants, args.calendar)
        save_variant_configs(variants, output_dir)
        generate_creative_specs(variants, output_dir / "creative_specs.csv")
        print("\nNext steps:")
        print(f"  1. CI will render variants from {output_dir}/")
        print(f"  2. Upload creative_specs.csv to Meta Ads Manager")
        print(f"  3. Run with --log-results results.csv after campaign")
        print(f"  4. Run with --recommend to pick winner")

    elif args.log_results:
        results = log_results(Path(args.log_results), figure_id)
        print("\n=== A/B Test Results ===")
        for vid, data in results.items():
            print(f"  {vid}: CTR={data['ctr']:.2f}% CPC=${data['cpc']:.2f} CVR={data['cvr']:.2f}% ROAS={data['roas']:.2f}x Spend=${data['spend']:.2f}")

        if args.recommend:
            winner = recommend_winner(results)
            print(f"\n=== Recommendation ===")
            print(f"  Winner: {winner.get('winner', 'None')}")
            print(f"  Reason: {winner.get('reason', 'N/A')}")

            if args.apply_winner and winner.get("winner"):
                design_pack_path = Path(f"design_pack/{figure_id}.json")
                if design_pack_path.exists():
                    update_render_overrides(figure_id, winner, design_pack_path)
                else:
                    print(f"Design pack not found: {design_pack_path}")


if __name__ == "__main__":
    main()