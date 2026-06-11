"""Run one full scrape-score-filter-report-push cycle."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

import batch_scorer
import filter_results
import notify
import report
import value_model
from desktop_app import DEFAULT_STATE
from fetch_list import DEFAULT_PAGE_SIZE
from score_accounts import DEFAULT_RULES


ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "logs" / "push_cycle.log"
RAW_OUTPUT = ROOT / "data" / "accounts_raw.json"
SCORE_OUTPUT = ROOT / "data" / "score_results_batch.json"
VALUE_OUTPUT = ROOT / "data" / "value_results.json"
FILTERED_OUTPUT = ROOT / "data" / "value_results_filtered.json"
REPORT_OUTPUT = ROOT / "reports" / "report_filtered.html"
PUSH_PREVIEW = ROOT / "reports" / "push_preview.html"
FILTERS_PATH = ROOT / "configs" / "app_filters.json"
VALUE_FORMULA_PATH = ROOT / "configs" / "value_formula.json"


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def load_filters() -> dict[str, object]:
    filters = dict(DEFAULT_STATE)
    if FILTERS_PATH.exists():
        filters.update(json.loads(FILTERS_PATH.read_text(encoding="utf-8")))
    return filters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只生成报告和推送预览，不实际推送到手机")
    args = parser.parse_args()

    LOG_PATH.write_text("", encoding="utf-8")
    old_safe_print = batch_scorer.safe_print
    batch_scorer.safe_print = log
    try:
        filters = load_filters()
        top_per_segment = int(float(str(filters.get("price_group_top_n") or 5)))
        log("Full cycle started" + (" (dry-run)" if args.dry_run else ""))
        log(f"Filters: {json.dumps(filters, ensure_ascii=False)}")

        batch = batch_scorer.run(
            pages=0,
            page_size=DEFAULT_PAGE_SIZE,
            limit=0,
            list_delay=2.0,
            detail_delay=0.2,
            raw_output=RAW_OUTPUT,
            score_output=SCORE_OUTPUT,
            rules=DEFAULT_RULES,
            top_n=top_per_segment,
            fetch_all=True,
            detail_workers=6,
            filters=filters,
            use_complete_list_snapshot=bool(filters.get("use_list_snapshot")),
        )
        log(
            "Scrape done: list=%s details=%s errors=%s scored=%s"
            % (
                batch["raw"]["source"].get("list_accounts"),
                batch["raw"]["total_accounts"],
                batch["raw"]["error_count"],
                batch["scored"]["total_accounts"],
            )
        )
        log(
            "List source=%s detail_candidates=%s prefilter_removed=%s snapshot_used=%s"
            % (
                batch["raw"]["source"].get("list_source"),
                batch["raw"]["source"].get("detail_candidates"),
                batch["raw"]["source"].get("prefilter_removed_count"),
                batch["raw"]["source"].get("list_complete_snapshot_used"),
            )
        )

        value = value_model.run(SCORE_OUTPUT, VALUE_OUTPUT, top_per_segment, VALUE_FORMULA_PATH)
        log(f"Value model done: accounts={value['total_accounts']}")

        filtered = filter_results.run(VALUE_OUTPUT, FILTERED_OUTPUT, filters)
        log(
            "Filter done: kept=%s removed=%s"
            % (filtered["total_accounts"], len(filtered.get("filtered_out") or []))
        )

        html = report.run(FILTERED_OUTPUT, REPORT_OUTPUT)
        log(f"Report done: bytes={len(html.encode('utf-8'))} path={REPORT_OUTPUT}")

        notify.run(
            input_path=FILTERED_OUTPUT,
            preview_path=PUSH_PREVIEW,
            top_n=top_per_segment,
            per_segment=top_per_segment,
            dry_run=args.dry_run,
        )
        log(("Preview done" if args.dry_run else "Push done") + f": preview={PUSH_PREVIEW}")
        return 0
    except Exception:
        log("Full cycle failed")
        log(traceback.format_exc())
        return 1
    finally:
        batch_scorer.safe_print = old_safe_print


if __name__ == "__main__":
    raise SystemExit(main())
