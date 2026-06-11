"""Fetch one page of Wuthering Waves listings from PXB7.

This is the first milestone crawler: it confirms the public list API and
normalizes the fields needed for later detail parsing and scoring.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GAME_ID = 10302
GAME_NAME = "鸣潮"
LIST_PAGE_URL = f"https://www.pxb7.com/seo/buy/{GAME_ID}/1"
LIST_API_URL = "https://www.pxb7.com/api/search/product/v2/selectSearchPageList"
LIST_API_FALLBACK_URLS = (
    "https://api-pc.pxb7.com/api/search/product/v2/selectSearchPageList",
)
PRODUCT_URL_TEMPLATE = "https://www.pxb7.com/product/{product_id}/1"

DEFAULT_PAGE_SIZE = 100
DEFAULT_OUTPUT = Path("data/sample_list.json")
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
RETRY_DELAYS = (2, 4, 8, 12)


def request_json(url: str, payload: dict[str, Any], referer: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Content-Type": "application/json",
                "Origin": "https://www.pxb7.com",
                "Referer": referer,
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_RETRIES - 1:
                break
            time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    raise last_error or RuntimeError("request failed")


def fetch_list_page(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    payload = {
        "query": "",
        "gameId": GAME_ID,
        "pageIndex": page,
        "pageSize": page_size,
        "bizProd": 1,
        "type": "4",
    }
    urls = (LIST_API_URL, *LIST_API_FALLBACK_URLS)
    last_error: Exception | None = None
    for url in urls:
        try:
            response = request_json(url, payload, LIST_PAGE_URL)
            response.setdefault("_request_url", url)
            return response
        except Exception as exc:
            last_error = exc
    raise last_error or RuntimeError("list request failed")


def yuan_from_cent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return None


def parse_count(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return int(match.group(1))


def split_attr_tags(tags: Any) -> dict[str, Any]:
    values = tags if isinstance(tags, list) else []
    server = values[0] if len(values) >= 1 else None
    sub_server = None
    if len(values) >= 2 and "TAP" not in str(values[1]) and "Wegame" not in str(values[1]):
        sub_server = values[1]
    tap_binding = next((tag for tag in values if "TAP" in str(tag)), None)
    wegame_binding = next((tag for tag in values if "Wegame" in str(tag)), None)
    return {
        "server": server,
        "sub_server": sub_server,
        "tap_binding": tap_binding,
        "wegame_binding": wegame_binding,
        "tags": values,
    }


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    product_id = str(item.get("productId") or "")
    title = item.get("showTitle") or item.get("productName") or ""
    attrs = split_attr_tags(item.get("attrNameList"))
    detail_url = PRODUCT_URL_TEMPLATE.format(product_id=product_id) if product_id else None
    level = parse_count(r"(\d+)级", title)
    five_star_characters = parse_count(r"(\d+)个五星角色", title)
    five_star_weapons = parse_count(r"(\d+)个五星武器", title)
    yellow_count = parse_count(r"(\d+)黄", title)

    return {
        "account_id": product_id,
        "product_unique_no": item.get("productUniqueNo"),
        "game_id": item.get("gameId"),
        "game_name": item.get("gameName"),
        "title": title,
        "price": yuan_from_cent(item.get("price")),
        "price_cent": item.get("price"),
        "detail_url": detail_url,
        "published_at": item.get("createTime"),
        "published_text": item.get("shelveUpTimeText"),
        "server": attrs["server"],
        "sub_server": attrs["sub_server"],
        "tap_binding": attrs["tap_binding"],
        "wegame_binding": attrs["wegame_binding"],
        "tags": attrs["tags"],
        "level": level,
        "yellow_count": yellow_count,
        "five_star_character_count": five_star_characters,
        "five_star_weapon_count": five_star_weapons,
        "image_count_pc": item.get("pcImgCount"),
        "image_count_h5": item.get("h5ImgCount"),
        "guarantee": item.get("guarantee"),
        "screenshot_type": item.get("screenshotType"),
        "main_image_url": item.get("mainImageUrl"),
        "raw": item,
    }


def run(page: int, page_size: int, output: Path) -> dict[str, Any]:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    response = fetch_list_page(page=page, page_size=page_size)
    if not response.get("success"):
        raise RuntimeError(
            "List API failed: %s %s"
            % (response.get("errCode"), response.get("errMessage") or response.get("msg"))
        )

    data = response.get("data") or {}
    raw_items = data.get("list") or []
    items = [normalize_item(item) for item in raw_items]
    result = {
        "source": {
            "site": "pxb7",
            "game_name": GAME_NAME,
            "game_id": GAME_ID,
            "list_page_url": LIST_PAGE_URL,
            "list_api_url": LIST_API_URL,
            "page": page,
            "page_size": page_size,
            "fetched_at": started_at,
        },
        "count": len(items),
        "items": items,
        "raw_properties": data.get("properties") or {},
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        result = run(args.page, args.page_size, args.output)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}")
        return 1
    except Exception as exc:
        print(f"Fetch failed: {exc}")
        return 1

    print(
        "Fetched {count} {game} listings from page {page}; saved to {path}".format(
            count=result["count"],
            game=result["source"]["game_name"],
            page=result["source"]["page"],
            path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
