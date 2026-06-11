"""Filter scored Wuthering Waves account value results."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/value_results.json")
DEFAULT_OUTPUT = Path("data/value_results_filtered.json")


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def split_words(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("，", ",").replace("、", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def owned_names(account: dict[str, Any], key: str) -> set[str]:
    source = account.get("source") or {}
    return {str(item.get("name")) for item in source.get(key) or [] if item.get("name")}


def has_risk_text(account: dict[str, Any], field: str, positive_words: tuple[str, ...]) -> bool:
    source = account.get("source") or {}
    flags = source.get("risk_flags") or {}
    text = str(flags.get(field) or "")
    return any(word in text for word in positive_words)


def hot_count(account: dict[str, Any]) -> int:
    source = account.get("source") or {}
    trade = source.get("trade") or {}
    return as_int(trade.get("hot_count"), 0)


def effective_pulls(account: dict[str, Any]) -> float:
    resource = (account.get("component_scores") or {}).get("resource") or {}
    return as_float(resource.get("estimated_pulls"), 0.0)


def parse_published_at(account: dict[str, Any]) -> datetime | None:
    source = account.get("source") or {}
    value = source.get("published_at") or account.get("published_at")
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            pass
    return None


def price_group_specs(filters: dict[str, Any]) -> list[tuple[str, float, float]]:
    start_value = filters.get("price_group_start") or filters.get("min_price")
    end_value = filters.get("price_group_end") or filters.get("max_price")
    step_value = filters.get("price_group_step")
    if start_value in ("", None) or end_value in ("", None) or step_value in ("", None):
        return []

    start = as_float(start_value)
    end = as_float(end_value)
    step = as_float(step_value)
    if step <= 0 or end <= start:
        return []

    specs = []
    low = start
    while low < end:
        high = min(low + step, end)
        specs.append((f"{int(low) if low.is_integer() else low:g}-{int(high) if high.is_integer() else high:g}", low, high))
        low = high
    return specs


def in_any_price_group(account: dict[str, Any], specs: list[tuple[str, float, float]]) -> bool:
    if not specs:
        return True
    price = as_float(account.get("price"), 0.0)
    return any(price >= low and price < high for _, low, high in specs)


def passes_filters(account: dict[str, Any], filters: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    price = as_float(account.get("price"), 0.0)
    total_score = as_float(account.get("total_score"), 0.0)
    value_score = as_float(account.get("value_score"), 0.0)
    source = account.get("source") or {}

    min_price = filters.get("min_price")
    if min_price not in ("", None) and price < as_float(min_price):
        reasons.append("价格低于下限")
    max_price = filters.get("max_price")
    if max_price not in ("", None) and price > as_float(max_price):
        reasons.append("价格高于上限")

    max_publish_age_days = filters.get("max_publish_age_days")
    if max_publish_age_days not in ("", None):
        published_at = parse_published_at(account)
        cutoff = datetime.now() - timedelta(days=as_float(max_publish_age_days))
        if published_at and published_at < cutoff:
            reasons.append("发布时间早于筛选天数")

    min_total_score = filters.get("min_total_score")
    if min_total_score not in ("", None) and total_score < as_float(min_total_score):
        reasons.append("总分不足")
    min_value_score = filters.get("min_value_score")
    if min_value_score not in ("", None) and value_score < as_float(min_value_score):
        reasons.append("性价比不足")

    min_five_star_characters = filters.get("min_five_star_characters")
    if min_five_star_characters not in ("", None):
        count = as_int(source.get("five_star_character_count"), len(source.get("characters") or []))
        if count < as_int(min_five_star_characters):
            reasons.append("五星角色数量不足")

    min_five_star_weapons = filters.get("min_five_star_weapons")
    if min_five_star_weapons not in ("", None):
        count = as_int(source.get("five_star_weapon_count"), len(source.get("weapons") or []))
        if count < as_int(min_five_star_weapons):
            reasons.append("五星武器数量不足")

    min_effective_pulls = filters.get("min_effective_pulls")
    if min_effective_pulls not in ("", None) and effective_pulls(account) < as_float(min_effective_pulls):
        reasons.append("等效抽数不足")

    min_collectible_score = filters.get("min_collectible_score")
    collectible_score = as_float(((account.get("component_scores") or {}).get("collectible") or {}).get("score"), 0.0)
    if min_collectible_score not in ("", None) and collectible_score < as_float(min_collectible_score):
        reasons.append("饰品分不足")

    max_hot_count = filters.get("max_hot_count")
    if max_hot_count not in ("", None) and hot_count(account) > as_int(max_hot_count):
        reasons.append("热度过高")

    if filters.get("require_bargain"):
        trade = source.get("trade") or {}
        if not trade.get("agree_bargain"):
            reasons.append("不支持议价")

    if filters.get("hide_tap_bound") and has_risk_text(account, "tap_binding", ("已绑定", "已绑")):
        reasons.append("TAP已绑定")
    if filters.get("hide_wegame_bound") and has_risk_text(account, "wegame_binding", ("已绑定", "已绑")):
        reasons.append("Wegame已绑定")
    if filters.get("hide_change_bind_cd"):
        cd = str(((source.get("risk_flags") or {}).get("change_bind_cd")) or "")
        if cd and "无" not in cd:
            reasons.append("存在换绑CD")

    required_characters = split_words(filters.get("required_characters"))
    if required_characters:
        chars = owned_names(account, "characters")
        missing = [name for name in required_characters if name not in chars]
        if missing:
            reasons.append("缺少指定角色：" + "、".join(missing))

    required_weapons = split_words(filters.get("required_weapons"))
    if required_weapons:
        weapons = owned_names(account, "weapons")
        missing = [name for name in required_weapons if name not in weapons]
        if missing:
            reasons.append("缺少指定武器：" + "、".join(missing))

    excluded_keywords = split_words(filters.get("excluded_keywords"))
    if excluded_keywords:
        text = "\n".join(str(source.get(key) or "") for key in ("title", "seller_remark"))
        hits = [word for word in excluded_keywords if word in text]
        if hits:
            reasons.append("命中排除词：" + "、".join(hits))

    return not reasons, reasons


def apply_filters(data: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    specs = price_group_specs(filters)
    kept = []
    removed = []
    for account in data.get("results") or []:
        ok, reasons = passes_filters(account, filters)
        if ok and not in_any_price_group(account, specs):
            ok = False
            reasons = ["不在指定价格分组范围内"]
        if ok:
            kept.append(account)
        else:
            removed.append(
                {
                    "account_id": account.get("account_id"),
                    "product_unique_no": account.get("product_unique_no"),
                    "price": account.get("price"),
                    "total_score": account.get("total_score"),
                    "value_score": account.get("value_score"),
                    "reasons": reasons,
                }
            )

    kept.sort(key=lambda item: item.get("value_score", 0), reverse=True)
    segments: dict[str, list[dict[str, Any]]] = {}
    top_per_segment = as_int(filters.get("price_group_top_n") or filters.get("top_per_segment"), 5)
    if specs:
        for name, low, high in specs:
            segment_accounts = [item for item in kept if as_float(item.get("price"), 0.0) >= low and as_float(item.get("price"), 0.0) < high]
            segment_accounts.sort(key=lambda item: item.get("value_score", 0), reverse=True)
            segments[name] = segment_accounts[:top_per_segment]
        kept = [item for accounts in segments.values() for item in accounts]
        kept.sort(key=lambda item: item.get("value_score", 0), reverse=True)
    else:
        for account in kept:
            segment = account.get("price_segment") or "unknown"
            segments.setdefault(segment, [])
        for segment in ("0-100", "100-300", "300-600", "600+"):
            segment_accounts = [item for item in kept if item.get("price_segment") == segment]
            segments[segment] = segment_accounts[:top_per_segment]

    return {
        "source": {
            **(data.get("source") or {}),
            "filters": filters,
            "filtered_out": len(removed),
            "price_group_specs": [{"name": name, "low": low, "high": high} for name, low, high in specs],
            "price_group_top_n": top_per_segment,
        },
        "total_accounts": len(kept),
        "results": kept,
        "segments": segments,
        "filtered_out": removed,
    }


def run(input_path: Path, output_path: Path, filters: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output = apply_filters(data, filters)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--filters-json", type=str, default="{}")
    args = parser.parse_args()
    filters = json.loads(args.filters_json)
    output = run(args.input, args.output, filters)
    print(f"Filtered value results: kept {output['total_accounts']}; saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
