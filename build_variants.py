#!/usr/bin/env python3
"""
Build multiple case variants from a design pack and variant matrix.

Usage:
    python build_variants.py --design-pack design_pack/panter_v1.json --matrix variant_matrix.json
    python build_variants.py --design-pack design_pack/panter_v1.json --matrix variant_matrix.json --filter "plinth_height=3.0"
    python build_variants.py --config config.json --matrix variant_matrix.json --name-prefix test_

Outputs:
    - output/print/panter_kilif_v2_{variant_id}.3mf
    - output/print/panter_kilif_v2_{variant_id}.stl
    - output/report/variant_comparison.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
PY = sys.executable


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_variants(matrix: dict, filters: list[str] = None) -> list[dict[str, Any]]:
    """Generate Cartesian product of variant values, apply filters."""
    axes = matrix.get("variants", {})
    keys = list(axes.keys())
    value_lists = [axes[k]["values"] for k in keys]

    variants = []
    for combo in itertools.product(*value_lists):
        variant = dict(zip(keys, combo))
        variant["_keys"] = keys

        # Apply filters
        if filters:
            skip = False
            for f in filters:
                if "=" in f:
                    k, v = f.split("=", 1)
                    # Try to parse v as number
                    try:
                        v_parsed = json.loads(v)
                    except json.JSONDecodeError:
                        v_parsed = v
                    if variant.get(k) != v_parsed:
                        skip = True
                        break
            if skip:
                continue

        variants.append(variant)

    return variants


def variant_id(variant: dict, naming: dict) -> str:
    """Generate variant ID from naming pattern."""
    pattern = naming.get("pattern", "variant_{}")
    sanitize = naming.get("sanitize", True)
    vid = pattern.format(**variant)
    if sanitize:
        vid = vid.replace(".", "p").replace(",", "_").replace(" ", "_")
    return vid


def run_build_case_v2(config_path: str, variant: dict, output_name: str, extra_args: list[str]) -> tuple[int, dict]:
    """Run build_case_v2.py with variant overrides. Returns (returncode, validation_report)."""
    # Build CLI args from variant
    cli_args = []
    supported = {
        "plinth_height": "--plinth-height",
        "hole_mode": "--hole-mode",
        "hole_diameter": "--hole-d",
    }

    for k, cli in supported.items():
        if k in variant:
            cli_args.extend([cli, str(variant[k])])

    cli_args.extend(["--name", output_name])
    cli_args.extend(extra_args)

    cmd = [PY, str(HERE / "build_case_v2.py"), "--config", config_path] + cli_args
    print(f"  Running: {' '.join(cmd)}", flush=True)

    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True, timeout=300)

    validation_report = {}
    print_check = {}
    if r.returncode == 0:
        # Parse validation report from stdout - find all top-level JSON objects
        try:
            # Use a simple state machine to extract JSON objects
            json_blocks = []
            brace_count = 0
            start_idx = None
            for i, ch in enumerate(r.stdout):
                if ch == '{':
                    if brace_count == 0:
                        start_idx = i
                    brace_count += 1
                elif ch == '}':
                    if brace_count > 0:
                        brace_count -= 1
                        if brace_count == 0 and start_idx is not None:
                            json_blocks.append(r.stdout[start_idx:i+1])
                            start_idx = None
            if len(json_blocks) >= 2:
                validation_report = json.loads(json_blocks[1])  # validation is typically the 2nd block
            elif len(json_blocks) == 1:
                validation_report = json.loads(json_blocks[0])
            if len(json_blocks) >= 3:
                print_check = json.loads(json_blocks[2])  # print_check is typically the 3rd block
        except Exception as e:
            print(f"  Warning: Could not parse validation JSON: {e}", file=sys.stderr)

    if r.returncode != 0:
        print(f"  FAILED: {r.stderr[:500]}", file=sys.stderr)

    return r.returncode, {"validation": validation_report, "print_check": print_check}


def estimate_print_time(validation: dict, layer_height: float = 0.12, speed_mm_s: float = 50) -> float:
    """Rough print time estimate from validation data (minutes)."""
    # This is a very rough heuristic
    volume = validation.get("print_check", {}).get("wall_thickness_mm", {}).get("p50", 1.0)
    # Use bounding box volume as proxy
    bbox = validation.get("validation", {}).get("bbox", {}).get("size", [60, 25, 63])
    est_volume = bbox[0] * bbox[1] * bbox[2] * 0.15  # ~15% infill
    # Very rough: volume mm³ / (speed * layer_height * extrusion_width) / 60
    return est_volume / (speed_mm_s * layer_height * 0.4) / 60


def estimate_filament(validation: dict, density: float = 1.24) -> float:
    """Estimate filament weight in grams from validation."""
    bbox = validation.get("validation", {}).get("bbox", {}).get("size", [60, 25, 63])
    volume = bbox[0] * bbox[1] * bbox[2] * 0.15  # mm³
    return volume * density / 1000  # grams


def main():
    ap = argparse.ArgumentParser(description="Build case variants from design pack + variant matrix")
    ap.add_argument("--design-pack", help="Path to design_pack JSON (relative to project root)")
    ap.add_argument("--config", help="Path to config.json (alternative to --design-pack)")
    ap.add_argument("--matrix", required=True, help="Path to variant_matrix.json")
    ap.add_argument("--filter", action="append", help="Filter variants (e.g., 'plinth_height=3.0')")
    ap.add_argument("--name-prefix", default="", help="Prefix for output file names")
    ap.add_argument("--extra-args", nargs=argparse.REMAINDER, help="Extra args passed to build_case_v2.py")
    ap.add_argument("--skip-validation", action="store_true", help="Skip validation step (faster)")
    args = ap.parse_args()

    # Load design pack or config
    if args.design_pack:
        design_pack_path = PROJECT_ROOT / args.design_pack
        if not design_pack_path.exists():
            # Try relative to current working directory
            design_pack_path_alt = Path.cwd() / args.design_pack
            if design_pack_path_alt.exists():
                design_pack_path = design_pack_path_alt
            else:
                sys.exit(f"Design pack not found: {design_pack_path} (also tried {design_pack_path_alt})")

        # Run load_design_pack.py to generate config.json
        cmd = [PY, str(HERE / "load_design_pack.py"), str(design_pack_path)]
        print(f"==> Loading design pack: {design_pack_path}")
        r = subprocess.run(cmd, cwd=HERE, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        if r.returncode != 0:
            sys.exit(f"load_design_pack.py failed: {r.stderr}")

        config_path = HERE / "config.json"
    elif args.config:
        config_path = Path(args.config)
    else:
        sys.exit("Either --design-pack or --config required")

    # Load variant matrix
    matrix_path = Path(args.matrix)
    if not matrix_path.is_absolute():
        matrix_path = HERE / matrix_path
    matrix = load_json(matrix_path)

    # Generate variants
    variants = generate_variants(matrix, args.filter)
    print(f"Generated {len(variants)} variant(s)")

    # Build each variant
    comparison = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "design_pack": args.design_pack,
        "config": str(config_path),
        "matrix": str(matrix_path),
        "variants": []
    }

    extra_args = args.extra_args or []
    if args.skip_validation:
        extra_args.append("--skip-selfint")
    else:
        # Always skip self-intersection check for variant builds (too slow)
        extra_args.append("--skip-selfint")

    for i, variant in enumerate(variants):
        vid = variant_id(variant, matrix.get("naming", {}))
        output_name = f"{args.name_prefix}{vid}"
        print(f"\n[{i+1}/{len(variants)}] Building variant: {vid}")
        print(f"  Params: {json.dumps({k: v for k, v in variant.items() if not k.startswith('_')}, ensure_ascii=False)}")

        # We need to modify config.json for this variant's unsupported params
        # Load base config, apply variant overrides, save temp config
        base_config = load_json(config_path)
        variant_config = json.loads(json.dumps(base_config))  # deep copy

        # Apply variant to config
        if "plinth_colour" in variant:
            variant_config.setdefault("case", {})["plinth_default_colour"] = variant["plinth_colour"]
        if "plinth_outset" in variant:
            variant_config.setdefault("case", {})["plinth_outset"] = variant["plinth_outset"]
        if "decimate_target_tris" in variant:
            variant_config.setdefault("case", {})["decimate_target_tris"] = variant["decimate_target_tris"]
        if "plinth_height" in variant:
            variant_config.setdefault("case", {})["plinth_height"] = variant["plinth_height"]
        if "hole_mode" in variant:
            variant_config.setdefault("case", {})["hole_mode"] = variant["hole_mode"]
        if "hole_diameter" in variant:
            variant_config.setdefault("case", {})["hole_diameter"] = variant["hole_diameter"]

        # Write temp config
        temp_config = HERE / f"config_variant_{vid}.json"
        save_json(temp_config, variant_config)

        try:
            rc, validation = run_build_case_v2(str(temp_config), variant, output_name, extra_args)
        finally:
            # Clean up temp config
            if temp_config.exists():
                temp_config.unlink()

        variant_result = {
            "variant_id": vid,
            "params": {k: v for k, v in variant.items() if not k.startswith('_')},
            "success": rc == 0,
            "output_name": output_name,
        }

        if rc == 0:
            # Extract metrics from validation
            # validation is now a dict with "validation" and "print_check" keys
            val = validation.get("validation", {})
            pc = validation.get("print_check", {})
            topology = val.get("topology", {})
            bbox = val.get("bbox", {}).get("size", [])
            volume = topology.get("signed_volume_mm3", 0)

            variant_result.update({
                "volume_mm3": round(volume, 1),
                "bbox_mm": [round(x, 1) for x in bbox],
                "print_time_est_min": round(estimate_print_time(validation), 1),
                "filament_est_g": round(estimate_filament(validation), 1),
                "estimated_cost_eur": round(estimate_filament(validation) * 0.025 + estimate_print_time(validation) * 8 / 60, 2),
                "wall_thickness_p50_mm": pc.get("wall_thickness_mm", {}).get("p50", 0),
                "overhang_gt60_area_mm2": val.get("overhang_gt60_area_mm2_total", 0),
                "self_intersections": topology.get("self_intersections", 0),
            })
            print(f"  ✓ Success: volume={variant_result['volume_mm3']}mm³, "
                  f"time≈{variant_result['print_time_est_min']}min, "
                  f"filament≈{variant_result['filament_est_g']}g, "
                  f"cost≈€{variant_result['estimated_cost_eur']}")
        else:
            variant_result["error"] = "Build failed"
            print(f"  ✗ Failed")

        comparison["variants"].append(variant_result)

    # Save comparison report
    report_path = HERE.parent.parent / "output" / "report" / "variant_comparison.json"
    save_json(report_path, comparison)

    # Print summary
    print("\n" + "=" * 80)
    print("VARIANT COMPARISON SUMMARY")
    print("=" * 80)
    successful = [v for v in comparison["variants"] if v["success"]]
    if successful:
        print(f"\n{'Variant ID':<50} {'Vol(mm³)':>10} {'Time(min)':>10} {'Fil(g)':>8} {'Cost(€)':>8} {'Wall(mm)':>8}")
        print("-" * 100)
        for v in successful:
            wall = v.get('wall_thickness_p50_mm', 0) or 0
            print(f"{v['variant_id']:<50} {v['volume_mm3']:>10.1f} {v['print_time_est_min']:>10.1f} "
                  f"{v['filament_est_g']:>8.1f} {v['estimated_cost_eur']:>8.2f} "
                  f"{wall:>8.3f}")

    failed = [v for v in comparison["variants"] if not v["success"]]
    if failed:
        print(f"\nFailed variants: {[v['variant_id'] for v in failed]}")

    print(f"\nFull report: {report_path}")

    # Exit with error if any failed
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()