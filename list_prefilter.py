"""Prefilter PXB7 list items before expensive detail requests."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

from filter_results import as_float, as_int, price_group_specs, split_words


RESOURCE_PULL_RULES = {
    "星声": 1 / 160,
    "月相": 1 / 160,
    "浮金波纹": 1,
    "余波珊瑚": 1 / 8,
    "铸潮波纹": 0,
}


def text_of(item: dict[str, Any]) -> str:
    return "\n".join(str(item.get(key) or "") for key in ("title", "product_unique_no", "server", "sub_server"))


def list_hot_count(item: dict[str, Any]) -> int:
    raw = item.get("raw") or {}
    return as_int(raw.get("hotCount") or raw.get("hot_count"), 0)


def list_resource_value(title: str, name: str) -> int:
    match = re.search(rf"{re.escape(name)}[:：]\s*(\d+)", title)
    return int(match.group(1)) if match else 0


def estimated_pulls_from_title(title: str) -> float:
    return round(sum(list_resource_value(title, name) * rate for name, rate in RESOURCE_PULL_RULES.items()), 2)


def parse_published_at(item: dict[str, Any]) -> datetime | None:
    value = item.get("published_at")
    if not value:
        raw = item.get("raw") or {}
        value = raw.get("createTime") or raw.get("shelveUpTime")
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            pass
    return None


def list_age_cutoff(filters: dict[str, Any] | None) -> datetime | None:
    if not filters:
        return None
    value = filters.get("max_publish_age_days")
    if value in ("", None):
        return None
    days = as_float(value, 0)
    if days <= 0:
        return None
    return datetime.now() - timedelta(days=days)


def item_older_than_cutoff(item: dict[str, Any], cutoff: datetime | None) -> bool:
    published_at = parse_published_at(item)
    return bool(cutoff and published_at and published_at < cutoff)


def list_rank_score(item: dict[str, Any]) -> float:
    title = str(item.get("title") or "")
    price = max(as_float(item.get("price"), 0.0), 1.0)
    five_star_characters = as_int(item.get("five_star_character_count"), 0)
    five_star_weapons = as_int(item.get("five_star_weapon_count"), 0)
    yellow_count = as_int(item.get("yellow_count"), 0)
    pulls = estimated_pulls_from_title(title)
    high_resonance_hits = len(re.findall(r"(满命|6命|5命|4命|3命|2命)", title))
    feature_score = (
        five_star_characters * 8
        + five_star_weapons * 5
        + high_resonance_hits * 3
        + pulls * 0.12
        + yellow_count * 0.05
    )
    return round(feature_score / (price ** 0.45), 4)


def limit_detail_candidates_by_price_group(
    kept: list[dict[str, Any]],
    filters: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    specs = price_group_specs(filters)
    limit = as_int(filters.get("prefilter_group_candidate_limit"), 0)
    if not specs or limit <= 0:
        return kept, []

    selected: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for segment_name, low, high in specs:
        segment = [
            item for item in kept
            if as_float(item.get("price"), 0.0) >= low and as_float(item.get("price"), 0.0) < high
        ]
        segment.sort(key=list_rank_score, reverse=True)
        for item in segment[:limit]:
            account_id = str(item.get("account_id") or "")
            selected_ids.add(account_id)
            item["_list_prefilter_segment"] = segment_name
            item["_list_prefilter_score"] = list_rank_score(item)
            selected.append(item)
        for item in segment[limit:]:
            removed.append(prefilter_removed_item(item, [f"列表粗排未入围：{segment_name} 前{limit}"]))

    return selected, removed


def is_b_server(item: dict[str, Any]) -> bool:
    text = text_of(item)
    return any(mark in text for mark in ("B服", "哔哩哔哩", "b服", "B站"))


def in_price_window(item: dict[str, Any], filters: dict[str, Any]) -> tuple[bool, str | None]:
    price = as_float(item.get("price"), 0.0)
    min_price = filters.get("min_price")
    if min_price not in ("", None) and price < as_float(min_price):
        return False, "价格低于下限"
    max_price = filters.get("max_price")
    if max_price not in ("", None) and price > as_float(max_price):
        return False, "价格高于上限"

    specs = price_group_specs(filters)
    if specs and not any(price >= low and price < high for _, low, high in specs):
        return False, "不在价格分组范围"
    return True, None


def passes_list_prefilter(item: dict[str, Any], filters: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    title = str(item.get("title") or "")
    full_text = text_of(item)

    cutoff = list_age_cutoff(filters)
    if item_older_than_cutoff(item, cutoff):
        reasons.append("发布时间早于筛选天数")

    if is_b_server(item):
        reasons.append("B服过滤")

    ok, price_reason = in_price_window(item, filters)
    if not ok and price_reason:
        reasons.append(price_reason)

    min_five_star_characters = filters.get("min_five_star_characters")
    if min_five_star_characters not in ("", None):
        if as_int(item.get("five_star_character_count"), 0) < as_int(min_five_star_characters):
            reasons.append("五星角色数量不足")

    min_five_star_weapons = filters.get("min_five_star_weapons")
    if min_five_star_weapons not in ("", None):
        if as_int(item.get("five_star_weapon_count"), 0) < as_int(min_five_star_weapons):
            reasons.append("五星武器数量不足")

    min_effective_pulls = filters.get("min_effective_pulls")
    if min_effective_pulls not in ("", None):
        if estimated_pulls_from_title(title) < as_float(min_effective_pulls):
            reasons.append("等效抽数不足")

    max_hot_count = filters.get("max_hot_count")
    if max_hot_count not in ("", None) and list_hot_count(item) > as_int(max_hot_count):
        reasons.append("热度过高")

    if filters.get("hide_tap_bound") and "已绑定TAP" in full_text:
        reasons.append("TAP已绑定")
    if filters.get("hide_wegame_bound") and ("已绑Wegame" in full_text or "已绑定Wegame" in full_text):
        reasons.append("Wegame已绑定")

    required_characters = split_words(filters.get("required_characters"))
    missing_characters = [name for name in required_characters if name not in title]
    if missing_characters:
        reasons.append("缺少指定角色：" + "、".join(missing_characters))

    required_weapons = split_words(filters.get("required_weapons"))
    missing_weapons = [name for name in required_weapons if name not in title]
    if missing_weapons:
        reasons.append("缺少指定武器：" + "、".join(missing_weapons))

    excluded_keywords = split_words(filters.get("excluded_keywords"))
    hits = [word for word in excluded_keywords if word in full_text]
    if hits:
        reasons.append("命中排除词：" + "、".join(hits))

    return not reasons, reasons


def apply_list_prefilter(
    items: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not filters:
        kept = []
        removed = []
        for item in items:
            if is_b_server(item):
                removed.append(prefilter_removed_item(item, ["B服过滤"]))
            else:
                kept.append(item)
        return kept, removed

    kept = []
    removed = []
    for item in items:
        ok, reasons = passes_list_prefilter(item, filters)
        if ok:
            kept.append(item)
        else:
            removed.append(prefilter_removed_item(item, reasons))
    capped, capped_removed = limit_detail_candidates_by_price_group(kept, filters)
    if capped_removed:
        return capped, [*removed, *capped_removed]
    return kept, removed


def prefilter_removed_item(item: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "account_id": item.get("account_id"),
        "product_unique_no": item.get("product_unique_no"),
        "price": item.get("price"),
        "title": item.get("title"),
        "reasons": reasons,
    }
