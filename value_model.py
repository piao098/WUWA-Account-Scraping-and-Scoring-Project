"""Compute value scores and price-segment recommendations."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = app_dir()
DEFAULT_INPUT = SCRIPT_DIR / "data" / "score_results_batch.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "value_results.json"
DEFAULT_FORMULA_CONFIG = SCRIPT_DIR / "configs" / "value_formula.json"
DEFAULT_VALUE_FORMULA = {
    "expected_base": 88.0,
    "expected_price_scale": 900.0,
    "expected_power": 0.62,
    "value_base": 50.0,
    "delta_weight": 1.35,
    "efficiency_multiplier": 100.0,
    "efficiency_cap": 30.0,
    "efficiency_weight": 0.25,
    "min_value_score": 0.0,
    "max_value_score": 100.0,
}

PRICE_SEGMENTS = (
    ("0-100", 0, 100),
    ("100-300", 100, 300),
    ("300-600", 300, 600),
    ("600+", 600, None),
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_formula(path: Path = DEFAULT_FORMULA_CONFIG) -> dict[str, float]:
    formula = dict(DEFAULT_VALUE_FORMULA)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        formula.update(data.get("value_formula") or data)
    return {key: float(value) for key, value in formula.items()}


def expected_score(price: float, formula: dict[str, float] | None = None) -> float:
    """A conservative price-to-score expectation curve.

    The curve rises quickly for low-price accounts and then flattens, so a
    strong cheap account gets a high value score while expensive whale accounts
    need much higher total scores to be considered underpriced.
    """

    if price <= 0:
        return 0.0
    cfg = formula or DEFAULT_VALUE_FORMULA
    base = float(cfg["expected_base"])
    scale = max(float(cfg["expected_price_scale"]), 1.0)
    power = float(cfg["expected_power"])
    return base * (1 - math.exp(-((price / scale) ** power)))


def price_segment(price: float) -> str:
    for name, low, high in PRICE_SEGMENTS:
        if price >= low and (high is None or price < high):
            return name
    return "unknown"


def enrich_value(account: dict[str, Any], formula: dict[str, float] | None = None) -> dict[str, Any]:
    cfg = formula or DEFAULT_VALUE_FORMULA
    price = float(account.get("price") or 0)
    total = float(account.get("total_score") or 0)
    expected = expected_score(price, cfg)
    value_delta = total - expected
    efficiency = total / max(price, 1) * float(cfg["efficiency_multiplier"])
    value_score = clamp(
        float(cfg["value_base"])
        + value_delta * float(cfg["delta_weight"])
        + min(efficiency, float(cfg["efficiency_cap"])) * float(cfg["efficiency_weight"]),
        float(cfg["min_value_score"]),
        float(cfg["max_value_score"]),
    )
    enriched = dict(account)
    enriched["expected_score"] = round(expected, 2)
    enriched["value_delta"] = round(value_delta, 2)
    enriched["price_efficiency"] = round(efficiency, 2)
    enriched["value_score"] = round(value_score, 2)
    enriched["price_segment"] = price_segment(price)
    return enriched


def run(
    input_path: Path,
    output_path: Path,
    top_per_segment: int,
    formula_path: Path = DEFAULT_FORMULA_CONFIG,
) -> dict[str, Any]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    formula = load_formula(formula_path)
    accounts = [enrich_value(item, formula) for item in data.get("results") or []]
    by_value = sorted(accounts, key=lambda item: item["value_score"], reverse=True)
    segments = {}
    for name, _, _ in PRICE_SEGMENTS:
        segment_accounts = [item for item in by_value if item["price_segment"] == name]
        segments[name] = segment_accounts[:top_per_segment]
    output = {
        "source": {
            "input": str(input_path),
            "top_per_segment": top_per_segment,
            "formula": formula,
        },
        "total_accounts": len(accounts),
        "results": by_value,
        "segments": segments,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-per-segment", type=int, default=5)
    parser.add_argument("--formula", type=Path, default=DEFAULT_FORMULA_CONFIG)
    args = parser.parse_args()
    result = run(args.input, args.output, args.top_per_segment, args.formula)
    non_empty = sum(1 for items in result["segments"].values() if items)
    print(
        f"Computed value_score for {result['total_accounts']} accounts; "
        f"{non_empty} price segments populated; saved to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
