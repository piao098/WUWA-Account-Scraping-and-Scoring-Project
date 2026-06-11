"""Fetch and parse Wuthering Waves product details from PXB7."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fetch_list import PRODUCT_URL_TEMPLATE, yuan_from_cent


DETAIL_API_URL = "https://www.pxb7.com/api/product/web/product/detail"
DETAIL_API_FALLBACK_URLS = (
    "https://api-pc.pxb7.com/api/product/web/product/detail",
)
DEFAULT_LIST_INPUT = Path("data/sample_list.json")
DEFAULT_OUTPUT = Path("data/sample_detail.json")
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
RETRY_DELAYS = (2, 4, 8, 12)


RESOURCE_NAMES = ("星声", "月相", "余波珊瑚", "浮金波纹", "铸潮波纹")
SECURITY_ATTR_NAMES = ("TAP绑定情况", "是否绑定Wegame", "是否有换绑CD", "按操作系统")
COLLECTIBLE_ATTRS = ("服饰", "摩托饰品", "涂装", "车架模组")
RESONANCE_ATTRS = ("一命角色", "二命角色", "三命角色", "四命角色", "五命角色", "满命角色")
REFINEMENT_ATTRS = ("精一武器", "精二武器", "精三武器", "精四武器", "精五武器")


def request_detail(product_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"productId": product_id})
    last_error: Exception | None = None
    for base_url in (DETAIL_API_URL, *DETAIL_API_FALLBACK_URLS):
        url = f"{base_url}?{query}"
        for attempt in range(MAX_RETRIES):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Origin": "https://www.pxb7.com",
                    "Referer": PRODUCT_URL_TEMPLATE.format(product_id=product_id),
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    data.setdefault("_request_url", base_url)
                    return data
            except Exception as exc:
                last_error = exc
                if attempt >= MAX_RETRIES - 1:
                    break
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    raise last_error or RuntimeError("detail request failed")


def int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def attr_map(detail: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in detail.get("reportTitleAttr") or []:
        name = item.get("attrName")
        value = item.get("attrValue")
        if name and value not in (None, ""):
            result[str(name)] = str(value)
    for item in detail.get("productAttrs") or detail.get("attrs") or []:
        name = item.get("attrName")
        vals = item.get("attrVals") or []
        if not name or not vals:
            continue
        first = vals[0]
        value = first.get("attrValue") or first.get("itemName")
        if value not in (None, ""):
            result[str(name)] = str(value)
    return result


def parse_count(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def parse_resource(name: str, text: str, attrs: dict[str, str]) -> int | None:
    if name in attrs:
        return int_or_none(attrs[name])
    return parse_count(rf"{re.escape(name)}：(\d+)", text)


def parse_level(text: str, attrs: dict[str, str]) -> int | None:
    return int_or_none(attrs.get("联觉等级")) or parse_count(r"(\d+)级", text)


def parse_character_token(token: str) -> dict[str, Any] | None:
    token = token.strip(" ，,；;")
    if not token:
        return None
    resonance = 0
    if token.startswith("满命"):
        resonance = 6
        name = token[2:].strip()
    else:
        match = re.match(r"(\d+)命(.+)", token)
        if match:
            resonance = int(match.group(1))
            name = match.group(2).strip()
        else:
            name = token
    return {"name": name, "resonance": resonance}


def parse_weapon_token(token: str) -> dict[str, Any] | None:
    token = token.strip(" ，,；;")
    if not token:
        return None
    refinement = None
    match = re.match(r"精(\d+)(.+)", token)
    if match:
        refinement = int(match.group(1))
        name = match.group(2).strip()
    else:
        name = token
    return {"name": name, "refinement": refinement}


def split_names(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    text = str(value).strip()
    text = re.sub(r"^(满命|[一二三四五六七八九十\d]+命|精\d+)", "", text)
    parts = re.split(r"[,，、;；]", text)
    return [part.strip() for part in parts if part.strip()]


def parse_structured_groups(attrs: dict[str, str], names: tuple[str, ...]) -> dict[str, list[str]]:
    return {name: split_names(attrs.get(name)) for name in names if split_names(attrs.get(name))}


def parse_section_items(text: str, label: str, parser) -> list[dict[str, Any]]:
    pattern = rf"\d+个{re.escape(label)}：(.+?)(?:；|;|$)"
    match = re.search(pattern, text)
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r"[,，]", raw)
    return [item for item in (parser(part) for part in parts) if item]


def parse_security(detail: dict[str, Any], attrs: dict[str, str], text: str) -> dict[str, Any]:
    max_amount = int_or_none(detail.get("maxGuaranteedAmount"))
    screenshot_source = None
    if "官方截图" in text:
        screenshot_source = "官方截图"
    elif "自主截图" in text:
        screenshot_source = "自主截图"
    return {
        "guarantee": detail.get("guarantee"),
        "max_guaranteed_amount": yuan_from_cent(max_amount),
        "server": attrs.get("按操作系统"),
        "tap_binding": attrs.get("TAP绑定情况"),
        "wegame_binding": attrs.get("是否绑定Wegame"),
        "change_bind_cd": attrs.get("是否有换绑CD"),
        "screenshot_source": screenshot_source,
    }


def parse_detail(detail: dict[str, Any]) -> dict[str, Any]:
    text = detail.get("showTitle") or ""
    attrs = attr_map(detail)
    characters = parse_section_items(text, "五星角色", parse_character_token)
    weapons = parse_section_items(text, "五星武器", parse_weapon_token)
    resources = {name: parse_resource(name, text, attrs) for name in RESOURCE_NAMES}
    security = parse_security(detail, attrs, text)
    collectibles = parse_structured_groups(attrs, COLLECTIBLE_ATTRS)
    resonance_groups = parse_structured_groups(attrs, RESONANCE_ATTRS)
    refinement_groups = parse_structured_groups(attrs, REFINEMENT_ATTRS)
    agree_bargain = detail.get("agreeBargain")
    bargain_status = detail.get("bargainStatus")
    bargain_price = yuan_from_cent(detail.get("bargainPrice"))

    return {
        "account_id": str(detail.get("productId") or ""),
        "product_unique_no": detail.get("productUniqueNo"),
        "game_id": str(detail.get("gameId") or ""),
        "game_name": detail.get("gameName"),
        "title": text,
        "price": yuan_from_cent(detail.get("price")),
        "price_cent": int_or_none(detail.get("price")),
        "detail_url": PRODUCT_URL_TEMPLATE.format(product_id=detail.get("productId")),
        "published_at": detail.get("shelveUpTime"),
        "published_text": detail.get("shelveUpTimeText"),
        "level": parse_level(text, attrs),
        "yellow_count": int_or_none(attrs.get("黄数")) or parse_count(r"(\d+)黄", text),
        "five_star_character_count": int_or_none(attrs.get("五星角色数量"))
        or parse_count(r"(\d+)个五星角色", text),
        "five_star_weapon_count": parse_count(r"(\d+)个五星武器", text),
        "characters": characters,
        "weapons": weapons,
        "resources": resources,
        "collectibles": collectibles,
        "resonance_groups": resonance_groups,
        "refinement_groups": refinement_groups,
        "server": security["server"],
        "risk_flags": {
            "tap_binding": security["tap_binding"],
            "wegame_binding": security["wegame_binding"],
            "change_bind_cd": security["change_bind_cd"],
            "guarantee": security["guarantee"],
            "screenshot_source": security["screenshot_source"],
        },
        "security": security,
        "main_important_keys": detail.get("mainImportantKeys") or [],
        "image_count": len(detail.get("images") or []),
        "images": detail.get("images") or [],
        "seller_remark": detail.get("sellerRemark"),
        "trade": {
            "agree_bargain": agree_bargain,
            "bargain_status": bargain_status,
            "bargain_price": bargain_price,
            "collect_count": detail.get("collectCount"),
            "hot_count": detail.get("hotCount"),
            "hot_count_text": detail.get("hotCountText"),
            "max_guaranteed_amount": security["max_guaranteed_amount"],
        },
        "raw_attrs": attrs,
        "raw": detail,
    }


def has_core_fields(item: dict[str, Any]) -> bool:
    resources = item.get("resources") or {}
    return all(
        [
            item.get("price") is not None,
            item.get("level") is not None,
            item.get("server"),
            item.get("characters"),
            item.get("weapons"),
            any(value is not None for value in resources.values()),
            item.get("risk_flags", {}).get("tap_binding") is not None,
            item.get("risk_flags", {}).get("wegame_binding") is not None,
        ]
    )


def choose_accounts(items: list[dict[str, Any]], sample_size: int, seed: int) -> list[dict[str, Any]]:
    if sample_size <= 0 or sample_size >= len(items):
        return items
    rng = random.Random(seed)
    return rng.sample(items, sample_size)


def run(list_input: Path, output: Path, sample_size: int, seed: int, delay: float) -> dict[str, Any]:
    source = json.loads(list_input.read_text(encoding="utf-8"))
    candidates = choose_accounts(source.get("items") or [], sample_size, seed)
    results = []
    errors = []

    for index, item in enumerate(candidates, 1):
        product_id = str(item.get("account_id") or "")
        if not product_id:
            errors.append({"account_id": product_id, "error": "missing account_id"})
            continue
        try:
            response = request_detail(product_id)
            if not response.get("success"):
                raise RuntimeError(response.get("errMessage") or response.get("msg") or "detail failed")
            parsed = parse_detail(response.get("data") or {})
            parsed["_sample_index"] = index
            parsed["_core_fields_ok"] = has_core_fields(parsed)
            results.append(parsed)
        except Exception as exc:
            errors.append({"account_id": product_id, "detail_url": item.get("detail_url"), "error": str(exc)})
        if delay > 0 and index < len(candidates):
            time.sleep(delay)

    output_data = {
        "source": {
            "detail_api_url": DETAIL_API_URL,
            "list_input": str(list_input),
            "sample_size": sample_size,
            "seed": seed,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "total_requested": len(candidates),
        "success_count": len(results),
        "core_fields_ok_count": sum(1 for item in results if item.get("_core_fields_ok")),
        "error_count": len(errors),
        "items": results,
        "errors": errors,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-input", type=Path, default=DEFAULT_LIST_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260611)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    try:
        result = run(args.list_input, args.output, args.sample_size, args.seed, args.delay)
    except Exception as exc:
        print(f"Detail fetch failed: {exc}")
        return 1

    print(
        "Fetched {ok}/{total} details; core fields ok {core}; errors {err}; saved to {path}".format(
            ok=result["success_count"],
            total=result["total_requested"],
            core=result["core_fields_ok_count"],
            err=result["error_count"],
            path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
