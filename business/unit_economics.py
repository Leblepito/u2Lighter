#!/usr/bin/env python3
"""
u2Lighter Unit Economics Calculator

Interactive calculator for COGS, pricing, break-even, and scenario analysis.
Can also generate Excel file for sharing with stakeholders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from pricing_calculator import (
    DEFAULTS,
    load_variant_comparison,
    extract_metrics,
    calculate_cogs,
    calculate_pricing,
    calculate_breakeven,
    calculate_scenarios,
)


def generate_excel(figure_id: str, result: dict, output_path: str) -> None:
    """Generate Excel file with all sheets."""
    if not PANDAS_AVAILABLE:
        print("pandas not installed. Install with: pip install pandas openpyxl", file=sys.stderr)
        return

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # COGS sheet
        cogs_df = pd.DataFrame([result["cogs"]])
        cogs_df.to_excel(writer, sheet_name="COGS", index=False)

        # Pricing sheet
        pricing_rows = []
        for channel, p in result["pricing"].items():
            row = {"channel": channel, **p}
            pricing_rows.append(row)
        pricing_df = pd.DataFrame(pricing_rows)
        pricing_df.to_excel(writer, sheet_name="Pricing", index=False)

        # Break-even sheet
        be_rows = []
        for channel, b in result["breakeven"].items():
            row = {"channel": channel, **b}
            be_rows.append(row)
        be_df = pd.DataFrame(be_rows)
        be_df.to_excel(writer, sheet_name="BreakEven", index=False)

        # Scenarios sheet
        scen_rows = []
        for name, s in result["scenarios"].items():
            row = {"scenario": name, **s}
            scen_rows.append(row)
        scen_df = pd.DataFrame(scen_rows)
        scen_df.to_excel(writer, sheet_name="Scenarios", index=False)

        # Assumptions sheet
        assum_df = pd.DataFrame([result["assumptions"]])
        assum_df.to_excel(writer, sheet_name="Assumptions", index=False)

        # Metrics sheet
        met_df = pd.DataFrame([result["metrics"]])
        met_df.to_excel(writer, sheet_name="Metrics", index=False)

    print(f"Excel report saved to {output_path}")


def print_tables(result: dict) -> None:
    """Print formatted tables to console."""
    print(f"\n{'='*60}")
    print(f"u2Lighter Unit Economics - {result['figure_id']}")
    print(f"{'='*60}")

    # COGS
    print(f"\n--- COGS (per unit) ---")
    for k, v in result["cogs"].items():
        print(f"  {k:30} €{v:>8.2f}")

    # Pricing
    print(f"\n--- Recommended Prices ---")
    print(f"  {'Channel':12} {'Price':>10} {'Margin €':>10} {'Margin %':>8} {'Multiplier':>10}")
    print(f"  {'-'*55}")
    for channel, p in result["pricing"].items():
        print(f"  {channel:12} €{p['recommended_price_eur']:>9.2f} €{p['margin_eur']:>9.2f} {p['margin_pct']:>7.1f}% {p['multiplier']:>10.1f}x")

    # Break-even
    print(f"\n--- Break-even (units/month) ---")
    print(f"  {'Channel':12} {'Fixed Costs':>12} {'Unit Margin':>12} {'Break-even':>12}")
    print(f"  {'-'*50}")
    for channel, b in result["breakeven"].items():
        be = b["breakeven_units_month"]
        be_str = f"{be:.0f}" if isinstance(be, (int, float)) else str(be)
        print(f"  {channel:12} €{b['fixed_costs_eur_month']:>11.2f} €{b['unit_margin_eur']:>11.2f} {be_str:>12}")

    # Scenarios
    print(f"\n--- Material Scenarios ---")
    print(f"  {'Scenario':20} {'Unit Cost':>10} {'DTC Price':>10} {'DTC Margin':>10}")
    print(f"  {'-'*52}")
    for name, s in result["scenarios"].items():
        if "unit_cost_eur" in s:
            print(f"  {name:20} €{s['unit_cost_eur']:>9.2f} €{s['dtc_price_eur']:>9.2f} {s['dtc_margin_pct']:>9.1f}%")

    # Printer scenarios
    print(f"\n--- Printer Count Scenarios ---")
    print(f"  {'Scenario':20} {'Fixed/Month':>12} {'DTC Break-even':>15}")
    print(f"  {'-'*50}")
    for name, s in result["scenarios"].items():
        if "fixed_costs_eur_month" in s:
            be = s["dtc_breakeven_units"]
            be_str = f"{be:.0f}" if isinstance(be, (int, float)) else str(be)
            print(f"  {name:20} €{s['fixed_costs_eur_month']:>11.2f} {be_str:>15}")


def main():
    ap = argparse.ArgumentParser(description="u2Lighter Unit Economics Calculator")
    ap.add_argument("--figure", required=True, help="Figure ID (e.g., panter_v1)")
    ap.add_argument("--excel", help="Output Excel file path")
    ap.add_argument("--json", help="Output JSON file path")
    ap.add_argument("--config", help="JSON config file to override assumptions")
    ap.add_argument("--quiet", action="store_true", help="Only output JSON/Excel, no console tables")
    args = ap.parse_args()

    # Load config
    assumptions = DEFAULTS.copy()
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            assumptions.update(json.load(f))

    # Load variant comparison
    try:
        variant_comparison = load_variant_comparison(args.figure)
        metrics = extract_metrics(variant_comparison, args.figure)
    except (FileNotFoundError, ValueError) as e:
        print(f"Warning: {e}. Using default metrics.", file=sys.stderr)
        metrics = {"filament_g": 17.5, "print_time_min": 98.0, "volume_mm3": 19785.9}

    # Calculate
    cogs = calculate_cogs(metrics, assumptions)
    pricing = calculate_pricing(cogs, assumptions)
    breakeven = calculate_breakeven(cogs, pricing, assumptions)
    scenarios = calculate_scenarios(metrics, assumptions)

    result = {
        "figure_id": args.figure,
        "metrics": metrics,
        "assumptions": assumptions,
        "cogs": cogs,
        "pricing": pricing,
        "breakeven": breakeven,
        "scenarios": scenarios,
    }

    if args.excel:
        generate_excel(args.figure, result, args.excel)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        if not args.quiet:
            print(f"JSON saved to {args.json}")

    if not args.quiet:
        print_tables(result)


if __name__ == "__main__":
    main()