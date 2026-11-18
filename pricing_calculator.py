#!/usr/bin/env python3
"""
u2Lighter Business Toolkit - Pricing Calculator

Usage:
    python pricing_calculator.py --figure panter_v1 --channel dtc --qty 100
    python pricing_calculator.py --figure panter_v1 --channel all --qty 500 --output pricing_report.json

Reads variant_comparison.json for filament/print time estimates, calculates COGS,
and outputs recommended prices per channel with margins.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Default assumptions (configurable via CLI or config file)
DEFAULTS = {
    "machine_rate_eur_h": 8.0,
    "filament_eur_kg": 25.0,
    "packaging_eur": 1.5,
    "labor_eur_per_unit": 0.5,
    "printer_depreciation_eur_month": 100.0,
    "software_eur_month": 50.0,
    "marketing_eur_month": 200.0,
    "rent_eur_month": 300.0,
    "channel_multipliers": {
        "wholesale": 2.2,
        "dtc": 5.0,
        "custom": 3.0,
        "custom_setup_fee": 50.0,
    },
    "vat_rate": 0.20,
}


def load_variant_comparison(figure_id: str) -> dict[str, Any]:
    """Load variant_comparison.json for the figure."""
    path = Path(f"output/report/variant_comparison.json")
    if not path.exists():
        # Try relative to project root
        path = Path(__file__).parent.parent / "output" / "report" / "variant_comparison.json"
    if not path.exists():
        raise FileNotFoundError(f"variant_comparison.json not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_metrics(variant_comparison: dict, figure_id: str) -> dict[str, float]:
    """Extract average filament_g and print_time_min from successful variants."""
    variants = variant_comparison.get("variants", [])
    successful = [v for v in variants if v.get("success", False)]
    if not successful:
        raise ValueError("No successful variants found in comparison")

    # Use the default variant (first successful) or average
    v = successful[0]
    return {
        "filament_g": v.get("filament_est_g", 17.5),
        "print_time_min": v.get("print_time_est_min", 98.0),
        "volume_mm3": v.get("volume_mm3", 19785.9),
    }


def calculate_cogs(metrics: dict, assumptions: dict) -> dict[str, float]:
    """Calculate Cost of Goods Sold per unit."""
    filament_cost = (metrics["filament_g"] / 1000) * assumptions["filament_eur_kg"]
    machine_cost = (metrics["print_time_min"] / 60) * assumptions["machine_rate_eur_h"]
    packaging_cost = assumptions["packaging_eur"]
    labor_cost = assumptions["labor_eur_per_unit"]

    unit_cost = filament_cost + machine_cost + packaging_cost + labor_cost

    return {
        "filament_cost_eur": round(filament_cost, 2),
        "machine_cost_eur": round(machine_cost, 2),
        "packaging_cost_eur": round(packaging_cost, 2),
        "labor_cost_eur": round(labor_cost, 2),
        "unit_cost_eur": round(unit_cost, 2),
    }


def calculate_pricing(cogs: dict, assumptions: dict) -> dict[str, Any]:
    """Calculate recommended prices per channel."""
    unit_cost = cogs["unit_cost_eur"]
    multipliers = assumptions["channel_multipliers"]

    pricing = {}
    for channel, mult in multipliers.items():
        if channel == "custom_setup_fee":
            continue
        price = round(unit_cost * mult, 2)
        margin_eur = round(price - unit_cost, 2)
        margin_pct = round((margin_eur / price) * 100, 1)
        pricing[channel] = {
            "recommended_price_eur": price,
            "margin_eur": margin_eur,
            "margin_pct": margin_pct,
            "multiplier": mult,
        }

    # Custom channel includes setup fee
    custom_price = round(unit_cost * multipliers["custom"] + multipliers["custom_setup_fee"], 2)
    custom_margin = round(custom_price - unit_cost - multipliers["custom_setup_fee"], 2)
    pricing["custom"] = {
        "recommended_price_eur": custom_price,
        "setup_fee_eur": multipliers["custom_setup_fee"],
        "unit_price_eur": round(unit_cost * multipliers["custom"], 2),
        "margin_eur": custom_margin,
        "margin_pct": round((custom_margin / custom_price) * 100, 1),
        "multiplier": multipliers["custom"],
    }

    return pricing


def calculate_breakeven(cogs: dict, pricing: dict, assumptions: dict) -> dict[str, Any]:
    """Calculate break-even units per month per channel."""
    fixed_costs = (
        assumptions["printer_depreciation_eur_month"]
        + assumptions["software_eur_month"]
        + assumptions["marketing_eur_month"]
        + assumptions["rent_eur_month"]
    )

    breakeven = {}
    for channel, p in pricing.items():
        margin = p["margin_eur"]
        if margin > 0:
            units = fixed_costs / margin
        else:
            units = float("inf")
        breakeven[channel] = {
            "fixed_costs_eur_month": round(fixed_costs, 2),
            "unit_margin_eur": round(margin, 2),
            "breakeven_units_month": round(units, 0) if units != float("inf") else "N/A",
        }

    return breakeven


def calculate_scenarios(metrics: dict, assumptions: dict) -> dict[str, Any]:
    """Calculate scenario analysis for different materials and setups."""
    base = assumptions.copy()
    scenarios = {}

    # Material scenarios
    materials = {
        "PLA": {"filament_eur_kg": 25.0, "machine_rate_eur_h": 8.0},
        "PETG": {"filament_eur_kg": 30.0, "machine_rate_eur_h": 8.5},
        "ASA": {"filament_eur_kg": 40.0, "machine_rate_eur_h": 9.0},
    }

    for name, overrides in materials.items():
        a = base.copy()
        a.update(overrides)
        cogs = calculate_cogs(metrics, a)
        pricing = calculate_pricing(cogs, a)
        scenarios[name] = {
            "unit_cost_eur": cogs["unit_cost_eur"],
            "dtc_price_eur": pricing["dtc"]["recommended_price_eur"],
            "dtc_margin_pct": pricing["dtc"]["margin_pct"],
        }

    # Printer count scenarios
    for printers in [1, 2, 3, 5]:
        a = base.copy()
        a["printer_depreciation_eur_month"] = 100.0 * printers
        a["rent_eur_month"] = 300.0 + 50.0 * (printers - 1)
        cogs = calculate_cogs(metrics, a)
        breakeven = calculate_breakeven(cogs, calculate_pricing(cogs, a), a)
        scenarios[f"{printers}_printers"] = {
            "fixed_costs_eur_month": a["printer_depreciation_eur_month"] + a["software_eur_month"] + a["marketing_eur_month"] + a["rent_eur_month"],
            "dtc_breakeven_units": breakeven["dtc"]["breakeven_units_month"],
        }

    return scenarios


def main():
    ap = argparse.ArgumentParser(description="u2Lighter Pricing Calculator")
    ap.add_argument("--figure", required=True, help="Figure ID (e.g., panter_v1)")
    ap.add_argument("--channel", choices=["wholesale", "dtc", "custom", "all"], default="all", help="Sales channel")
    ap.add_argument("--qty", type=int, default=100, help="Quantity for volume pricing")
    ap.add_argument("--output", help="Output JSON file path")
    ap.add_argument("--config", help="JSON config file to override assumptions")
    ap.add_argument("--show-assumptions", action="store_true", help="Print default assumptions and exit")
    args = ap.parse_args()

    if args.show_assumptions:
        print(json.dumps(DEFAULTS, indent=2))
        return

    # Load custom config if provided
    assumptions = DEFAULTS.copy()
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            assumptions.update(json.load(f))

    # Load variant comparison
    try:
        variant_comparison = load_variant_comparison(args.figure)
    except FileNotFoundError as e:
        print(f"Warning: {e}. Using default metrics.", file=sys.stderr)
        metrics = {"filament_g": 17.5, "print_time_min": 98.0, "volume_mm3": 19785.9}
    else:
        metrics = extract_metrics(variant_comparison, args.figure)

    # Calculate
    cogs = calculate_cogs(metrics, assumptions)
    pricing = calculate_pricing(cogs, assumptions)
    breakeven = calculate_breakeven(cogs, pricing, assumptions)
    scenarios = calculate_scenarios(metrics, assumptions)

    result = {
        "figure_id": args.figure,
        "quantity": args.qty,
        "metrics": metrics,
        "assumptions": assumptions,
        "cogs": cogs,
        "pricing": {k: v for k, v in pricing.items() if args.channel in ("all", k)},
        "breakeven": breakeven,
        "scenarios": scenarios,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {args.output}")

    # Print summary
    print(f"\n=== u2Lighter Pricing Calculator ===")
    print(f"Figure: {args.figure}")
    print(f"Quantity: {args.qty}")
    print(f"\n--- COGS ---")
    for k, v in cogs.items():
        print(f"  {k}: €{v}")
    print(f"\n--- Recommended Prices ---")
    for channel, p in pricing.items():
        if args.channel == "all" or args.channel == channel:
            print(f"  {channel:12}: €{p['recommended_price_eur']:.2f} (margin: {p['margin_pct']}%)")
    print(f"\n--- Break-even (units/month) ---")
    for channel, b in breakeven.items():
        be = b["breakeven_units_month"]
        print(f"  {channel:12}: {be}")

    return result


if __name__ == "__main__":
    main()