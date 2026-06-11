"""Validate the normalized detail sample against the project schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/sample_detail.json")
DEFAULT_MAX_MISSING_RATE = 0.20


CORE_FIELDS = (
    "account_id",
    "price",
    "title",
    "detail_url",
    "level",
    "server",
    "characters",
    "weapons",
    "resources",
    "risk_flags",
)


def is_present(value: Any, field: str) -> bool:
    if value in (None, ""):
        return False
    if field in {"characters", "weapons"}:
        return isinstance(value, list) and len(value) > 0
    if field == "resources":
        return isinstance(value, dict) and any(v is not None for v in value.values())
    if field == "risk_flags":
        return isinstance(value, dict) and any(v not in (None, "") for v in value.values())
    return True


def validate(path: Path, max_missing_rate: float) -> tuple[bool, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") or []
    total_slots = len(items) * len(CORE_FIELDS)
    missing_by_field = {}
    for field in CORE_FIELDS:
        missing_by_field[field] = sum(1 for item in items if not is_present(item.get(field), field))
    missing_total = sum(missing_by_field.values())
    missing_rate = missing_total / total_slots if total_slots else 1.0
    report = {
        "input": str(path),
        "accounts": len(items),
        "core_fields": len(CORE_FIELDS),
        "missing_total": missing_total,
        "missing_rate": round(missing_rate, 4),
        "max_missing_rate": max_missing_rate,
        "missing_by_field": missing_by_field,
    }
    return missing_rate <= max_missing_rate, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--max-missing-rate", type=float, default=DEFAULT_MAX_MISSING_RATE)
    args = parser.parse_args()

    ok, report = validate(args.input, args.max_missing_rate)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
