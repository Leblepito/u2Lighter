#!/usr/bin/env python3
"""
Load a Design Pack JSON and produce:
- config.json (merged with defaults)
- render_args.json (for turntable.py)

Usage:
    python load_design_pack.py design_pack/panter_v1.json
    python load_design_pack.py design_pack/panter_v1.json --output-config config.json --output-render render_args.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:
    print("jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SCHEMA_PATH = HERE / "design_pack_schema.json"
DEFAULT_CONFIG_PATH = HERE / "config.json"


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning new dict."""
    result = json.loads(json.dumps(base))  # deep copy
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def design_pack_to_config(design_pack: dict, base_config: dict) -> dict:
    """Merge design_pack geometry_overrides into base config."""
    overrides = design_pack.get("geometry_overrides", {})
    return deep_merge(base_config, overrides)


def design_pack_to_render_args(design_pack: dict) -> dict:
    """Extract render overrides and add marketing info."""
    render_overrides = design_pack.get("render_overrides", {})
    marketing = design_pack.get("marketing", {})

    # Convert to turntable.py CLI arguments format
    args = {}
    mapping = {
        "start_phi": "--start-phi",
        "direction": "--direction",
        "profile": "--profile",
        "lens": "--lens",
        "elev": "--elev",
        "light_scale": "--light-scale",
        "margin": "--margin",
        "seconds": "--seconds",
        "samples": "--samples",
        "noise": "--noise",
        "res": "--res",
        "pct": "--pct",
        "no_lighter": "--no-lighter",
        "case": "--case",
    }

    for key, cli_flag in mapping.items():
        if key in render_overrides:
            value = render_overrides[key]
            if isinstance(value, bool):
                if value:
                    args[cli_flag] = True
            else:
                args[cli_flag] = value

    # Add marketing config for export_marketing.py
    args["_marketing"] = marketing
    args["_figure_id"] = design_pack["figure_id"]

    return args


def validate_design_pack(design_pack: dict, schema: dict) -> None:
    """Validate design_pack against schema."""
    try:
        jsonschema.validate(instance=design_pack, schema=schema)
    except jsonschema.ValidationError as e:
        print(f"Design Pack validation error: {e.message}", file=sys.stderr)
        print(f"Path: {' -> '.join(str(p) for p in e.path)}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Load Design Pack and generate config.json + render_args.json")
    ap.add_argument("design_pack", help="Path to design_pack JSON file")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Base config.json path")
    ap.add_argument("--schema", default=str(SCHEMA_PATH), help="Schema JSON path")
    ap.add_argument("--output-config", default=str(HERE / "config.json"), help="Output config.json path")
    ap.add_argument("--output-render", default=str(HERE / "render_args.json"), help="Output render_args.json path")
    ap.add_argument("--dry-run", action="store_true", help="Print merged config without writing")
    args = ap.parse_args()

    # Load schema
    schema = load_json(Path(args.schema))

    # Load design pack
    design_pack_path = Path(args.design_pack)
    if not design_pack_path.is_absolute():
        # project root is 2 levels up from pipeline/geometry/ (pipeline/geometry -> pipeline -> u2Lighter)
        project_root = HERE
        design_pack_path = project_root / design_pack_path
    design_pack = load_json(design_pack_path)

    # Validate
    validate_design_pack(design_pack, schema)
    print(f"✓ Design Pack '{design_pack['figure_id']}' validated")

    # Load base config
    base_config = load_json(Path(args.config))

    # Merge
    merged_config = design_pack_to_config(design_pack, base_config)
    render_args = design_pack_to_render_args(design_pack)

    if args.dry_run:
        print("\n=== Merged config.json ===")
        print(json.dumps(merged_config, indent=2, ensure_ascii=False))
        print("\n=== render_args.json ===")
        print(json.dumps(render_args, indent=2, ensure_ascii=False))
        return

    # Write outputs
    save_json(Path(args.output_config), merged_config)
    save_json(Path(args.output_render), render_args)

    print(f"✓ Written config: {args.output_config}")
    print(f"✓ Written render args: {args.output_render}")
    print(f"✓ Figure: {design_pack['figure_id']} ({design_pack['source']})")


if __name__ == "__main__":
    main()