"""Run the full PXB7 Wuthering Waves evaluation pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import batch_scorer
import report
import value_model
from fetch_list import DEFAULT_PAGE_SIZE


LOG_FILE = Path("logs/run_all.log")
ERROR_FILE = Path("data/errors.json")


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def write_errors(errors: list[dict[str, Any]]) -> None:
    ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    ERROR_FILE.write_text(json.dumps({"errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    log("Pipeline started")
    log(
        "Batch params: pages=%s page_size=%s limit=%s top_n=%s"
        % (args.pages, args.page_size, args.limit, args.top_n)
    )
    batch = batch_scorer.run(
        pages=args.pages,
        page_size=args.page_size,
        limit=args.limit,
        list_delay=args.list_delay,
        detail_delay=args.detail_delay,
        raw_output=args.raw_output,
        score_output=args.score_output,
        rules=args.rules,
        top_n=args.top_n,
    )
    write_errors(batch["raw"].get("errors") or [])
    log(
        "Batch done: raw=%s errors=%s scored=%s"
        % (
            batch["raw"]["total_accounts"],
            batch["raw"]["error_count"],
            batch["scored"]["total_accounts"],
        )
    )

    value = value_model.run(args.score_output, args.value_output, args.top_per_segment)
    log("Value model done: accounts=%s" % value["total_accounts"])

    html = report.run(args.value_output, args.report_output)
    log("Report done: %s bytes -> %s" % (len(html.encode("utf-8")), args.report_output))
    log("Pipeline finished")
    return {"batch": batch, "value": value, "report_bytes": len(html.encode("utf-8"))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--list-delay", type=float, default=1.0)
    parser.add_argument("--detail-delay", type=float, default=0.2)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--top-per-segment", type=int, default=5)
    parser.add_argument("--raw-output", type=Path, default=Path("data/accounts_raw.json"))
    parser.add_argument("--score-output", type=Path, default=Path("data/score_results_batch.json"))
    parser.add_argument("--value-output", type=Path, default=Path("data/value_results.json"))
    parser.add_argument("--report-output", type=Path, default=Path("reports/report.html"))
    parser.add_argument("--rules", type=Path, default=Path("configs/scoring_rules.json"))
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except Exception as exc:
        log(f"Pipeline failed: {exc}")
        log(traceback.format_exc())
        write_errors([{"stage": "run_all", "error": str(exc), "traceback": traceback.format_exc()}])
        return 1


if __name__ == "__main__":
    sys.exit(main())
