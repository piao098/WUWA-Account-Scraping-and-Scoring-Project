"""Fetch, parse, and score a batch of Wuthering Waves accounts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from fetch_detail import has_core_fields, parse_detail, request_detail
from fetch_list import DEFAULT_PAGE_SIZE, GAME_ID, GAME_NAME, fetch_list_page, normalize_item
from list_prefilter import apply_list_prefilter, item_older_than_cutoff, list_age_cutoff
from score_accounts import DEFAULT_RULES, is_filtered_server, load_character_tiers, load_team_rules, score_account


DEFAULT_RAW_OUTPUT = Path("data/accounts_raw.json")
DEFAULT_SCORE_OUTPUT = Path("data/score_results_batch.json")
DEFAULT_LIST_CHECKPOINT = Path("data/list_checkpoint.json")
DEFAULT_LIST_COMPLETE = Path("data/list_complete.json")
DEFAULT_DETAIL_CHECKPOINT = Path("data/detail_checkpoint.json")
LIST_PAGE_RETRY_DELAYS = (60, 120, 240)
LIST_CHECKPOINT_EVERY_PAGES = 5
DETAIL_CHECKPOINT_EVERY_ITEMS = 50


def safe_print(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(path)


def checkpoint_suffix(complete_scope: str, filter_signature: dict[str, Any] | None = None) -> str:
    if complete_scope == "full" and not filter_signature:
        return ""
    payload = json.dumps(filter_signature or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(f"{complete_scope}:{payload}".encode("utf-8")).hexdigest()[:10]
    return f"_{complete_scope}_{digest}"


def list_checkpoint_path(
    complete_scope: str = "full",
    filter_signature: dict[str, Any] | None = None,
) -> Path:
    suffix = checkpoint_suffix(complete_scope, filter_signature)
    if not suffix:
        return DEFAULT_LIST_CHECKPOINT
    return DEFAULT_LIST_CHECKPOINT.with_name(f"{DEFAULT_LIST_CHECKPOINT.stem}{suffix}{DEFAULT_LIST_CHECKPOINT.suffix}")


def write_list_checkpoint(
    items: list[dict[str, Any]],
    page: int,
    page_size: int,
    complete: bool,
    error: str | None = None,
    complete_scope: str = "full",
    filter_signature: dict[str, Any] | None = None,
) -> None:
    data = {
        "source": {
            "site": "pxb7",
            "game_id": GAME_ID,
            "game_name": GAME_NAME,
            "page": page,
            "page_size": page_size,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "complete": complete,
            "complete_scope": complete_scope,
            "filter_signature": filter_signature or {},
            "error": error,
        },
        "count": len(items),
        "items": items,
    }
    write_json_atomic(list_checkpoint_path(complete_scope, filter_signature), data)
    if complete and complete_scope == "full":
        write_json_atomic(DEFAULT_LIST_COMPLETE, data)


def load_complete_list(page_size: int) -> list[dict[str, Any]] | None:
    if not DEFAULT_LIST_COMPLETE.exists():
        return None
    try:
        data = json.loads(DEFAULT_LIST_COMPLETE.read_text(encoding="utf-8"))
    except Exception:
        return None
    source = data.get("source") or {}
    if not source.get("complete"):
        return None
    if source.get("complete_scope", "full") != "full":
        return None
    items = data.get("items") or []
    return items or None


def load_list_checkpoint(
    page_size: int,
    complete_scope: str = "full",
    filter_signature: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int] | None:
    path = list_checkpoint_path(complete_scope, filter_signature)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    source = data.get("source") or {}
    if source.get("complete"):
        return None
    if int(source.get("page_size") or 0) != int(page_size):
        return None
    if source.get("complete_scope", "full") != complete_scope:
        return None
    if (source.get("filter_signature") or {}) != (filter_signature or {}):
        return None
    items = data.get("items") or []
    if not items:
        return None
    page = int(source.get("page") or 1)
    next_page = page + 1 if source.get("complete") else page
    return items, max(1, next_page)


def load_detail_checkpoint(selected_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not DEFAULT_DETAIL_CHECKPOINT.exists():
        return [], []
    try:
        data = json.loads(DEFAULT_DETAIL_CHECKPOINT.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    details_by_id = {}
    for item in data.get("items") or []:
        account_id = str(item.get("account_id") or "")
        if account_id in selected_ids and account_id not in details_by_id:
            details_by_id[account_id] = item
    details = list(details_by_id.values())
    errors = [
        item for item in data.get("errors") or []
        if str(item.get("account_id") or "") in selected_ids
    ]
    return details, errors


def write_detail_checkpoint(
    details: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    total_requested: int,
    selected_ids: set[str],
    complete: bool,
) -> None:
    data = {
        "source": {
            "site": "pxb7",
            "game_id": GAME_ID,
            "game_name": GAME_NAME,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "complete": complete,
        },
        "total_requested": total_requested,
        "selected_ids": sorted(selected_ids),
        "total_accounts": len(details),
        "core_fields_ok_count": sum(1 for item in details if item.get("_core_fields_ok")),
        "error_count": len(errors),
        "items": details,
        "errors": errors,
    }
    write_json_atomic(DEFAULT_DETAIL_CHECKPOINT, data)


def fetch_list_pages(pages: int, page_size: int, delay: float) -> list[dict[str, Any]]:
    seen = set()
    items: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        response = fetch_list_page(page=page, page_size=page_size)
        if not response.get("success"):
            raise RuntimeError(
                "List page %s failed: %s %s"
                % (page, response.get("errCode"), response.get("errMessage") or response.get("msg"))
            )
        raw_items = (response.get("data") or {}).get("list") or []
        for raw in raw_items:
            normalized = normalize_item(raw)
            account_id = normalized.get("account_id")
            if account_id and account_id not in seen:
                seen.add(account_id)
                items.append(normalized)
        safe_print(f"List page {page}: +{len(raw_items)} raw, total unique {len(items)}")
        write_list_checkpoint(items, page=page, page_size=page_size, complete=page == pages)
        if delay > 0 and page < pages:
            time.sleep(delay)
    return items


def fetch_all_list_pages(
    page_size: int,
    delay: float,
    max_pages: int = 10000,
    use_complete_snapshot: bool = False,
    filters: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_info: dict[str, Any] = {
        "list_source": "live",
        "list_complete_snapshot_used": False,
    }
    if use_complete_snapshot:
        complete_items = load_complete_list(page_size)
        if complete_items:
            safe_print(f"List snapshot: use last complete list with {len(complete_items)} accounts")
            return complete_items, {
                "list_source": "complete_snapshot",
                "list_complete_snapshot_used": True,
            }
    cutoff = list_age_cutoff(filters)
    complete_scope = "age_cutoff" if cutoff else "full"
    filter_signature = (
        {"max_publish_age_days": str((filters or {}).get("max_publish_age_days") or "")}
        if cutoff
        else {}
    )
    checkpoint = load_list_checkpoint(page_size, complete_scope, filter_signature)
    if checkpoint:
        items, page = checkpoint
        seen = {str(item.get("account_id") or "") for item in items if item.get("account_id")}
        safe_print(f"List checkpoint: resume page {page}, total unique {len(items)}")
    else:
        seen = set()
        items = []
        page = 1
    while page <= max_pages:
        response = None
        last_exc: Exception | None = None
        for retry_index, retry_delay in enumerate((0, *LIST_PAGE_RETRY_DELAYS), 1):
            if retry_delay:
                safe_print(f"List page {page}: wait {retry_delay}s before retry {retry_index - 1}")
                time.sleep(retry_delay)
            try:
                response = fetch_list_page(page=page, page_size=page_size)
                break
            except Exception as exc:
                last_exc = exc
                write_list_checkpoint(
                    items,
                    page=page,
                    page_size=page_size,
                    complete=False,
                    error=str(exc),
                    complete_scope=complete_scope,
                    filter_signature=filter_signature,
                )
        if response is None:
            raise last_exc or RuntimeError(f"List page {page} failed")
        if not response.get("success"):
            write_list_checkpoint(
                items,
                page=page,
                page_size=page_size,
                complete=False,
                complete_scope=complete_scope,
                filter_signature=filter_signature,
                error=response.get("errMessage") or response.get("msg"),
            )
            raise RuntimeError(
                "List page %s failed: %s %s"
                % (page, response.get("errCode"), response.get("errMessage") or response.get("msg"))
            )
        raw_items = (response.get("data") or {}).get("list") or []
        new_count = 0
        normalized_page = []
        for raw in raw_items:
            normalized = normalize_item(raw)
            normalized_page.append(normalized)
            account_id = normalized.get("account_id")
            if account_id and account_id not in seen:
                seen.add(account_id)
                items.append(normalized)
                new_count += 1
        safe_print(f"List page {page}: +{len(raw_items)} raw, +{new_count} new, total unique {len(items)}")
        if normalized_page and item_older_than_cutoff(normalized_page[0], cutoff):
            write_list_checkpoint(
                items,
                page=page,
                page_size=page_size,
                complete=True,
                complete_scope="age_cutoff",
                filter_signature=filter_signature,
            )
            source_info.update(
                {
                    "list_source": "live_age_cutoff",
                    "list_complete_snapshot_used": False,
                    "list_stopped_by_age_cutoff": True,
                    "list_stop_page": page,
                    "list_cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S") if cutoff else None,
                }
            )
            break
        if not raw_items or len(raw_items) < page_size:
            write_list_checkpoint(
                items,
                page=page,
                page_size=page_size,
                complete=True,
                complete_scope=complete_scope,
                filter_signature=filter_signature,
            )
            source_info.update({"list_source": "live_complete", "list_complete_snapshot_used": False})
            break
        if page % LIST_CHECKPOINT_EVERY_PAGES == 0:
            write_list_checkpoint(
                items,
                page=page,
                page_size=page_size,
                complete=False,
                complete_scope=complete_scope,
                filter_signature=filter_signature,
            )
        page += 1
        if delay > 0:
            time.sleep(delay)
    return items, source_info


def fetch_one_detail(index: int, total: int, item: dict[str, Any]) -> tuple[int, str, dict[str, Any] | None, dict[str, Any] | None]:
    account_id = str(item.get("account_id") or "")
    if not account_id:
        return index, account_id, None, {"account_id": account_id, "error": "missing account_id"}
    try:
        response = request_detail(account_id)
        if not response.get("success"):
            raise RuntimeError(response.get("errMessage") or response.get("msg") or "detail failed")
        parsed = parse_detail(response.get("data") or {})
        parsed["_batch_index"] = index
        parsed["_core_fields_ok"] = has_core_fields(parsed)
        return index, account_id, parsed, None
    except Exception as exc:
        return index, account_id, None, {"account_id": account_id, "detail_url": item.get("detail_url"), "error": str(exc)}


def fetch_details(
    list_items: list[dict[str, Any]],
    limit: int,
    delay: float,
    workers: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = list_items[:limit] if limit > 0 else list_items
    selected_ids = {str(item.get("account_id") or "") for item in selected if item.get("account_id")}
    details, errors = load_detail_checkpoint(selected_ids)
    done_ids = {str(item.get("account_id") or "") for item in details}
    if details:
        safe_print(f"Detail checkpoint: reuse {len(details)} ok, {len(errors)} errors")
    pending = [
        (index, item)
        for index, item in enumerate(selected, 1)
        if str(item.get("account_id") or "") not in done_ids
    ]
    pending_ids = {str(item.get("account_id") or "") for _, item in pending}
    errors = [error for error in errors if str(error.get("account_id") or "") not in pending_ids]

    worker_count = max(1, int(workers or 1))
    if worker_count == 1:
        completed = 0
        for index, item in pending:
            _, account_id, parsed, error = fetch_one_detail(index, len(selected), item)
            completed += 1
            if parsed:
                details.append(parsed)
                done_ids.add(account_id)
                safe_print(f"Detail {index}/{len(selected)}: {account_id} ok")
            elif error:
                errors.append(error)
                safe_print(f"Detail {index}/{len(selected)}: {account_id} error {error.get('error')}")
            if completed % DETAIL_CHECKPOINT_EVERY_ITEMS == 0:
                write_detail_checkpoint(details, errors, total_requested=len(selected), selected_ids=selected_ids, complete=False)
            if delay > 0 and index < len(selected):
                time.sleep(delay)
    else:
        safe_print(f"Detail workers: {worker_count}; pending {len(pending)} / {len(selected)}")
        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = []
            for index, item in pending:
                futures.append(executor.submit(fetch_one_detail, index, len(selected), item))
                if delay > 0:
                    time.sleep(delay)
            for future in as_completed(futures):
                index, account_id, parsed, error = future.result()
                completed += 1
                if parsed:
                    details.append(parsed)
                    done_ids.add(account_id)
                    safe_print(f"Detail {index}/{len(selected)}: {account_id} ok")
                elif error:
                    errors.append(error)
                    safe_print(f"Detail {index}/{len(selected)}: {account_id} error {error.get('error')}")
                if completed % DETAIL_CHECKPOINT_EVERY_ITEMS == 0:
                    write_detail_checkpoint(
                        details,
                        errors,
                        total_requested=len(selected),
                        selected_ids=selected_ids,
                        complete=False,
                    )
    write_detail_checkpoint(details, errors, total_requested=len(selected), selected_ids=selected_ids, complete=True)
    return details, errors


def write_raw(
    details: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    output: Path,
    pages: int,
    page_size: int,
    prefilter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "source": {
            "site": "pxb7",
            "game_id": GAME_ID,
            "game_name": GAME_NAME,
            "pages": pages,
            "page_size": page_size,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "prefilter": prefilter or {},
        },
        "total_accounts": len(details),
        "core_fields_ok_count": sum(1 for item in details if item.get("_core_fields_ok")),
        "error_count": len(errors),
        "items": details,
        "errors": errors,
    }
    write_json_atomic(output, data)
    return data


def score_details(details: list[dict[str, Any]], rules_path: Path, output: Path, top_n: int) -> dict[str, Any]:
    load_character_tiers.cache_clear()
    load_team_rules.cache_clear()
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    filtered = [account for account in details if is_filtered_server(account)]
    scorable_details = [account for account in details if not is_filtered_server(account)]
    results = [score_account(account, rules) for account in scorable_details]
    results.sort(key=lambda item: item["total_score"], reverse=True)
    data = {
        "source": {
            "rules": str(rules_path),
            "rules_version": rules.get("version"),
            "scored_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "filtered_b_server_count": len(filtered),
        },
        "total_accounts": len(results),
        "filtered_accounts": len(filtered),
        "top_n": top_n,
        "top_accounts": results[:top_n],
        "results": results,
    }
    write_json_atomic(output, data)
    return data


def run(
    pages: int,
    page_size: int,
    limit: int,
    list_delay: float,
    detail_delay: float,
    raw_output: Path,
    score_output: Path,
    rules: Path,
    top_n: int,
    fetch_all: bool = True,
    detail_workers: int = 1,
    filters: dict[str, Any] | None = None,
    use_complete_list_snapshot: bool = False,
) -> dict[str, Any]:
    if fetch_all:
        list_items, list_source_info = fetch_all_list_pages(
            page_size=page_size,
            delay=list_delay,
            use_complete_snapshot=use_complete_list_snapshot,
            filters=filters,
        )
        detail_limit = 0
        page_count = -1
    else:
        list_items = fetch_list_pages(pages=pages, page_size=page_size, delay=list_delay)
        list_source_info = {"list_source": "live_paged", "list_complete_snapshot_used": False}
        detail_limit = limit
        page_count = pages
    prefilter_kept, prefilter_removed = apply_list_prefilter(list_items, filters)
    prefilter_info = {
        "enabled": True,
        "list_accounts": len(list_items),
        "detail_candidates": len(prefilter_kept),
        "removed": len(prefilter_removed),
        "removed_examples": prefilter_removed[:50],
    }
    safe_print(
        "List prefilter: %s -> %s detail candidates, removed %s"
        % (len(list_items), len(prefilter_kept), len(prefilter_removed))
    )
    details, errors = fetch_details(prefilter_kept, limit=detail_limit, delay=detail_delay, workers=detail_workers)
    raw = write_raw(details, errors, raw_output, pages=page_count, page_size=page_size, prefilter=prefilter_info)
    raw["source"]["fetch_all"] = fetch_all
    raw["source"]["list_accounts"] = len(list_items)
    raw["source"].update(list_source_info)
    raw["source"]["detail_candidates"] = len(prefilter_kept)
    raw["source"]["prefilter_removed_count"] = len(prefilter_removed)
    write_json_atomic(raw_output, raw)
    scored = score_details(details, rules_path=rules, output=score_output, top_n=top_n)
    return {"raw": raw, "scored": scored}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--paged", action="store_true", help="只抓取指定页数；默认抓完所有列表页")
    parser.add_argument("--list-delay", type=float, default=2.0)
    parser.add_argument("--detail-delay", type=float, default=0.2)
    parser.add_argument("--detail-workers", type=int, default=6)
    parser.add_argument("--use-list-snapshot", action="store_true", help="使用最近一次完整列表快照，跳过列表重扫")
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--score-output", type=Path, default=DEFAULT_SCORE_OUTPUT)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()

    result = run(
        pages=args.pages,
        page_size=args.page_size,
        limit=args.limit,
        list_delay=args.list_delay,
        detail_delay=args.detail_delay,
        raw_output=args.raw_output,
        score_output=args.score_output,
        rules=args.rules,
        top_n=args.top_n,
        fetch_all=not args.paged,
        detail_workers=args.detail_workers,
        use_complete_list_snapshot=args.use_list_snapshot,
    )
    print(
        "Batch done: details {details}, errors {errors}, scored {scored}, top {top}".format(
            details=result["raw"]["total_accounts"],
            errors=result["raw"]["error_count"],
            scored=result["scored"]["total_accounts"],
            top=len(result["scored"]["top_accounts"]),
        )
    )
    return 0 if result["raw"]["total_accounts"] >= min(args.limit, args.pages * args.page_size) else 1


if __name__ == "__main__":
    raise SystemExit(main())
