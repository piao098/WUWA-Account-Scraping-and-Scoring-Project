"""Generate a readable HTML report from value results."""

from __future__ import annotations

import argparse
import html
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/value_results.json")
DEFAULT_OUTPUT = Path("reports/report.html")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def short_assets(account: dict[str, Any]) -> tuple[str, str, str]:
    source = account.get("source") or {}
    characters = source.get("characters") or []
    weapons = source.get("weapons") or []
    resources = source.get("resources") or {}
    char_text = "、".join(
        f"{c.get('name')}({c.get('resonance')}链)" for c in characters[:8]
    )
    weapon_text = "、".join(
        f"{w.get('name')}{'' if w.get('refinement') is None else ' 精' + str(w.get('refinement'))}"
        for w in weapons[:6]
    )
    resource_text = " | ".join(f"{k}:{v}" for k, v in resources.items() if v is not None)
    return char_text, weapon_text, resource_text


def account_card(account: dict[str, Any], index: int) -> str:
    char_text, weapon_text, resource_text = short_assets(account)
    reasons = account.get("reasons") or []
    deductions = account.get("deductions") or []
    source = account.get("source") or {}
    risk_flags = source.get("risk_flags") or {}
    return f"""
    <article class="card">
      <div class="rank">#{index}</div>
      <div class="main">
        <div class="line title">
          <a href="{esc(account.get('detail_url'))}" target="_blank">{esc(account.get('product_unique_no') or account.get('account_id'))}</a>
          <span class="price">¥{esc(account.get('price'))}</span>
          <span class="tag">总分 {esc(account.get('total_score'))}</span>
          <span class="tag value">性价比 {esc(account.get('value_score'))}</span>
        </div>
        <div class="line muted">等级 {esc(account.get('level'))} | {esc(account.get('server'))} | 期望分 {esc(account.get('expected_score'))} | 超额 {esc(account.get('value_delta'))}</div>
        <div class="line"><b>角色</b>：{esc(char_text)}</div>
        <div class="line"><b>武器</b>：{esc(weapon_text)}</div>
        <div class="line"><b>资源</b>：{esc(resource_text)}</div>
        <div class="line"><b>推荐</b>：{esc('；'.join(reasons) if reasons else '暂无')}</div>
        <div class="line"><b>风险</b>：{esc('；'.join(deductions) if deductions else '未见明显扣分')} | {esc(risk_flags)}</div>
      </div>
    </article>
    """


def render_report(data: dict[str, Any]) -> str:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    segments = data.get("segments") or {}
    section_html = []
    for name, accounts in segments.items():
        cards = "\n".join(account_card(account, i) for i, account in enumerate(accounts, 1))
        if not cards:
            cards = '<p class="empty">本价格段暂无候选。</p>'
        section_html.append(f"<section><h2>{esc(name)} 元</h2>{cards}</section>")

    top_total = sorted(data.get("results") or [], key=lambda item: item.get("total_score", 0), reverse=True)[:20]
    top_value = (data.get("results") or [])[:20]
    total_cards = "\n".join(account_card(account, i) for i, account in enumerate(top_total, 1))
    value_cards = "\n".join(account_card(account, i) for i, account in enumerate(top_value, 1))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>螃蟹鸣潮账号评估报告</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #202124; background: #f6f7f9; }}
    header {{ padding: 24px 32px; background: #ffffff; border-bottom: 1px solid #e5e7eb; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .meta {{ color: #6b7280; font-size: 13px; }}
    .card {{ display: grid; grid-template-columns: 48px 1fr; gap: 12px; padding: 14px; margin: 10px 0; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }}
    .rank {{ font-size: 18px; font-weight: 700; color: #f08a20; }}
    .line {{ margin: 4px 0; font-size: 13px; line-height: 1.55; }}
    .title {{ font-size: 15px; font-weight: 700; }}
    .price {{ margin-left: 10px; color: #d93025; }}
    .tag {{ display: inline-block; margin-left: 8px; padding: 2px 6px; border-radius: 4px; background: #eef2ff; color: #334155; font-size: 12px; }}
    .value {{ background: #ecfdf5; color: #047857; }}
    .muted {{ color: #6b7280; }}
    a {{ color: #2563eb; text-decoration: none; }}
    .tabs {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    .empty {{ color: #6b7280; background: #fff; border: 1px solid #e5e7eb; padding: 14px; border-radius: 8px; }}
  </style>
</head>
<body>
  <header>
    <h1>螃蟹鸣潮账号评估报告</h1>
    <div class="meta">生成时间：{esc(generated_at)} | 账号数：{esc(data.get('total_accounts'))} | 指标：总分、性价比、推荐理由、风险提示</div>
  </header>
  <main>
    <section>
      <h2>性价比 Top 20</h2>
      {value_cards}
    </section>
    <section>
      <h2>总分 Top 20</h2>
      {total_cards}
    </section>
    {''.join(section_html)}
  </main>
</body>
</html>"""


def run(input_path: Path, output_path: Path) -> str:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    html_text = render_report(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return html_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    html_text = run(args.input, args.output)
    print(f"Report written to {args.output} ({len(html_text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
