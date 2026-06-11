"""Push final Wuthering Waves account scores via PushPlus.

The formatting follows the cangbaoge project's idea: compact summary first,
collapsible account cards, price segments, and risk/reason details. This script
does not store tokens in code. It reads notify_config.json from this project,
or falls back to the existing cangbaoge notify_config.json when present.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = app_dir()
CONFIG_CANDIDATES = (
    SCRIPT_DIR / "notify_config.json",
    Path(r"G:\code base\cangbaoge\notify_config.json"),
)
DEFAULT_INPUT = SCRIPT_DIR / "data" / "value_results.json"
DEFAULT_PREVIEW = SCRIPT_DIR / "reports" / "push_preview.html"
PUSHPLUS_URL = "http://www.pushplus.plus/send"


def load_config() -> dict[str, Any]:
    for path in CONFIG_CANDIDATES:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("notify_config.json not found in project or cangbaoge fallback")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def tier_color(tier: Any) -> str:
    colors = {
        "T0": "#e74c3c",
        "T0.5": "#e67e22",
        "T1": "#f39c12",
        "T2": "#27ae60",
        "T3": "#7f8c8d",
        "T4": "#95a5a6",
        "T-1": "#9b59b6",
    }
    return colors.get(str(tier or ""), "#64748b")


def resonance_color(resonance: Any) -> str:
    try:
        value = int(resonance)
    except (TypeError, ValueError):
        value = 0
    colors = {
        0: "#64748b",
        1: "#0891b2",
        2: "#2563eb",
        3: "#4f46e5",
        4: "#7c3aed",
        5: "#c026d3",
        6: "#dc2626",
    }
    return colors.get(max(0, min(6, value)), "#64748b")


def tier_class(tier: Any) -> str:
    value = str(tier or "").replace(".", "").replace("-", "m").lower()
    return f"t{value}" if value else "tx"


def resonance_class(resonance: Any) -> str:
    try:
        value = int(resonance)
    except (TypeError, ValueError):
        value = 0
    return f"r{max(0, min(6, value))}"


def character_detail_map(account: dict[str, Any]) -> dict[str, dict[str, Any]]:
    character_score = (account.get("component_scores") or {}).get("character") or {}
    return {
        str(item.get("name")): item
        for item in character_score.get("role_details") or []
        if item.get("name")
    }


def format_character(item: dict[str, Any]) -> str:
    return f"{item.get('name', '')}({item.get('resonance', 0)}链)"


def format_character_html(item: dict[str, Any], details: dict[str, dict[str, Any]] | None = None) -> str:
    name = str(item.get("name") or "")
    resonance = item.get("resonance", 0)
    detail = (details or {}).get(name) or {}
    tier = detail.get("tier")
    tier_label = f"[{tier}]" if tier else ""
    signature_refinement = detail.get("signature_refinement_total")
    if signature_refinement is not None:
        value_text = f"{resonance}+{signature_refinement or 0}"
    else:
        value_text = f"{resonance}链"
    return (
        '<span class="ch">'
        f'<span class="{tier_class(tier)}"><b>{esc(name)}</b>{esc(tier_label)}</span>'
        f'<span class="rb {resonance_class(resonance)}">{esc(value_text)}</span>'
        "</span>"
    )


def format_weapon(item: dict[str, Any]) -> str:
    refinement = item.get("refinement")
    return f"{item.get('name', '')}{'' if refinement is None else ' 精' + str(refinement)}"


def format_items(items: list[dict[str, Any]], key: str) -> str:
    parts = []
    for item in items:
        if key == "character":
            parts.append(format_character(item))
        else:
            parts.append(format_weapon(item))
    return "、".join(parts)


def signature_weapon_names(account: dict[str, Any]) -> set[str]:
    details = character_detail_map(account)
    return {
        str(item.get("signature_weapon"))
        for item in details.values()
        if item.get("signature_weapon") and item.get("signature_refinement_total")
    }


def non_signature_weapons(account: dict[str, Any]) -> list[dict[str, Any]]:
    source = account.get("source") or {}
    signature_names = signature_weapon_names(account)
    return [
        item for item in source.get("weapons") or []
        if str(item.get("name") or "") not in signature_names
    ]


def grouped_character_text(account: dict[str, Any]) -> str:
    source = account.get("source") or {}
    character_items = source.get("characters") or []
    by_name = {str(item.get("name")): item for item in character_items if item.get("name")}
    details = character_detail_map(account)
    character_score = (account.get("component_scores") or {}).get("character") or {}
    groups = character_score.get("completed_team_groups") or []
    used: set[str] = set()
    lines = []

    for group in groups:
        if group.get("check_type") == "owned_only":
            continue
        members = [str(name) for name in (group.get("members") or []) if name in by_name]
        if len(members) < 2:
            continue
        if any(name in used for name in members):
            continue
        if len(set(members)) != len(members):
            continue
        used.update(members)
        member_text = " + ".join(format_character_html(by_name[name], details) for name in members)
        lines.append(f"成型队：{member_text}")

    remaining = [
        format_character_html(item, details)
        for item in character_items
        if item.get("name") not in used
    ]
    if remaining:
        lines.append("其他角色：" + "、".join(remaining))
    return "<br>".join(lines) if lines else "暂无"


def character_score_detail(account: dict[str, Any]) -> str:
    character_score = (account.get("component_scores") or {}).get("character") or {}
    details = character_score.get("role_details") or []
    if not details:
        return "暂无"
    parts = []
    for item in details[:12]:
        matched_team = item.get("matched_team") or []
        team = "+配队" if item.get("team_flag") and len(matched_team) >= 2 else ""
        if item.get("team_flag") and item.get("team_check_type") == "owned_only":
            team = "+泛用"
        weapon = ""
        if item.get("signature_refinement_total"):
            weapon = f"+专武精{item.get('signature_refinement_total')}"
        parts.append(
            '<span class="sr">'
            f'<span class="{tier_class(item.get("tier"))}"><b>{esc(item.get("name"))}</b>'
            f'[{esc(item.get("tier"))}]</span> '
            f'{esc(item.get("score"))}分('
            f'<span class="{resonance_class(item.get("resonance"))}">{esc(item.get("resonance"))}链</span>'
            f'{esc(weapon)}{esc(team)})'
            "</span>"
        )
    return "、".join(parts)


def collectible_names_detail(account: dict[str, Any]) -> str:
    collectible = (account.get("component_scores") or {}).get("collectible") or {}
    detail = collectible.get("detail") or {}
    if not detail:
        return "暂无"
    parts = []
    for category, names in detail.items():
        if names:
            parts.append(f"{category}：" + "、".join(str(name) for name in names))
    return "；".join(parts) if parts else "暂无"


def resource_pulls_detail(account: dict[str, Any]) -> str:
    resource = (account.get("component_scores") or {}).get("resource") or {}
    pulls = resource.get("estimated_pulls")
    if pulls in (None, ""):
        return "暂无"
    return f"{pulls}抽"


def trade_heat_text(account: dict[str, Any]) -> str:
    source = account.get("source") or {}
    trade = source.get("trade") or {}
    hot_text = trade.get("hot_count_text")
    hot_count = trade.get("hot_count")
    if hot_text:
        return str(hot_text)
    if hot_count is not None:
        return str(hot_count)
    return "暂无"


def risk_review_html(account: dict[str, Any]) -> str:
    source = account.get("source") or {}
    flags = source.get("risk_flags") or {}
    items = []

    tap = str(flags.get("tap_binding") or "")
    if "已绑定" in tap or "已绑" in tap:
        items.append(f"TAP：{tap}")

    wegame = str(flags.get("wegame_binding") or "")
    if "已绑定" in wegame or "已绑" in wegame:
        items.append(f"Wegame：{wegame}")

    cd = str(flags.get("change_bind_cd") or "")
    if cd and "无" not in cd:
        items.append(f"换绑CD：{cd}")

    if not items:
        return ""
    return f"<p><b>风险：</b>{esc('；'.join(items))}</p>"


def account_html(account: dict[str, Any], index: int) -> str:
    source = account.get("source") or {}
    character_items = source.get("characters") or []
    all_weapon_items = source.get("weapons") or []
    weapon_items = non_signature_weapons(account)
    chars = grouped_character_text(account)
    weapons = format_items(weapon_items, "weapon") or "专武已并入角色"
    collectible_text = collectible_names_detail(account)
    resource_pulls = resource_pulls_detail(account)
    resources = source.get("resources") or {}
    resource_text = " | ".join(f"{k}:{v}" for k, v in resources.items() if v is not None)
    reasons = "；".join(account.get("reasons") or []) or "暂无"
    heat = trade_heat_text(account)
    risk_html = risk_review_html(account)
    return f"""
<details class="card">
  <summary>
    <b>{index}. ¥{esc(account.get("price"))}</b>
    <span class="tag">总分 {esc(account.get("total_score"))}</span>
    <span class="tag good">性价比 {esc(account.get("value_score"))}</span>
    <span class="tag">角色 {len(character_items)}</span>
    <span class="tag">武器 {len(all_weapon_items)}</span>
    <span class="muted">{esc(account.get("product_unique_no") or account.get("account_id"))}</span>
  </summary>
  <div class="body">
    <p class="muted">等级 {esc(account.get("level"))} | {esc(account.get("server"))} | 期望分 {esc(account.get("expected_score"))} | 超额 {esc(account.get("value_delta"))}</p>
    <p><b>角色：</b><br>{chars}</p>
    <p><b>武器：</b>{esc(weapons)}</p>
    <p><b>资源：</b>{esc(resource_text)}</p>
    <p><b>等效限定抽：</b>{esc(resource_pulls)}</p>
    <p><b>饰品：</b>{esc(collectible_text)}</p>
    <p><b>推荐：</b>{esc(reasons)}</p>
    <p><b>热度：</b>{esc(heat)}</p>
    {risk_html}
    <p><a href="{esc(account.get("detail_url"))}">打开螃蟹详情</a></p>
  </div>
</details>
"""


def section(title: str, accounts: list[dict[str, Any]]) -> str:
    if not accounts:
        return f"<h2>{esc(title)}</h2><p class='muted'>暂无候选。</p>"
    cards = "\n".join(account_html(acc, i) for i, acc in enumerate(accounts, 1))
    return f"<h2>{esc(title)}</h2>{cards}"


def style_lines() -> list[str]:
    return [
        "<style>",
        ".wrap{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:680px;margin:0 auto;color:#202124;}",
        ".meta{color:#667085;font-size:13px;line-height:1.6}",
        ".card{border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;padding:10px 12px;margin:10px 0;}",
        ".card summary{cursor:pointer;line-height:1.7}",
        ".body{font-size:13px;line-height:1.6;margin-top:8px}",
        ".ch,.sr{display:inline-block;margin:1px 2px 1px 0;white-space:nowrap;}",
        ".rb{font-size:12px;margin-left:2px;font-weight:600;}",
        ".tt0{color:#e74c3c}.tt05{color:#e67e22}.tt1{color:#f39c12}.tt2{color:#27ae60}.tt3{color:#7f8c8d}.tt4{color:#95a5a6}.ttm1{color:#9b59b6}.tx{color:#64748b}",
        ".r0{color:#64748b}.r1{color:#0891b2}.r2{color:#2563eb}.r3{color:#4f46e5}.r4{color:#7c3aed}.r5{color:#c026d3}.r6{color:#dc2626}",
        ".tag{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:4px;background:#eef2ff;color:#334155;font-size:12px}",
        ".good{background:#ecfdf5;color:#047857}",
        ".muted{color:#667085;font-size:12px}",
        "h1{font-size:21px;border-bottom:2px solid #f08a20;padding-bottom:8px}",
        "h2{font-size:16px;margin:18px 0 8px;border-left:4px solid #f08a20;padding-left:8px}",
        "a{color:#2563eb;text-decoration:none}",
        "</style>",
    ]


def message_open(data: dict[str, Any], generated_at: str, heading: str) -> list[str]:
    return [
        *style_lines(),
        "<div class='wrap'>",
        f"<h1>{esc(heading)}</h1>",
        f"<p class='meta'>推送时间：{esc(generated_at)} | 评分账号：{esc(data.get('total_accounts'))} 个 | 角色梯度/链数使用递进颜色；交易与风险仅供人工审核</p>",
    ]


def format_chunk_message(data: dict[str, Any], heading: str, sections: list[tuple[str, list[dict[str, Any]]]]) -> str:
    generated_at = time.strftime("%Y-%m-%d %H:%M")
    parts = message_open(data, generated_at, heading)
    for title, accounts in sections:
        parts.append(section(title, accounts))
    parts.append("</div>")
    return "\n".join(parts)


def format_message(data: dict[str, Any], top_n: int, per_segment: int) -> str:
    results = data.get("results") or []
    top_value = results[:top_n]
    top_score = sorted(results, key=lambda item: item.get("total_score", 0), reverse=True)[:top_n]
    segments = data.get("segments") or {}
    generated_at = time.strftime("%Y-%m-%d %H:%M")
    best = top_value[0] if top_value else {}

    parts = message_open(data, generated_at, "螃蟹鸣潮账号最终评分")
    if best:
        parts.append(
            "<p class='meta'><b>当前性价比第一：</b>"
            f"¥{esc(best.get('price'))} | 总分 {esc(best.get('total_score'))} | "
            f"性价比 {esc(best.get('value_score'))} | {esc(best.get('product_unique_no') or best.get('account_id'))}</p>"
        )

    parts.append(section(f"性价比 Top {top_n}", top_value))
    parts.append(section(f"总分 Top {top_n}", top_score))

    for name, accounts in segments.items():
        parts.append(section(f"{name} 元性价比 Top {per_segment}", (accounts or [])[:per_segment]))

    parts.append("<p class='muted'>提示：评分为自动模型结果，最终购买还需人工核对截图、绑定状态、找回包赔和卖家说明。</p>")
    parts.append("</div>")
    return "\n".join(parts)


def send_pushplus(token: str, title: str, content: str, config: dict[str, Any] | None = None) -> bool:
    payload = {"token": token, "title": title, "content": content, "template": "html"}
    config = config or {}
    topic = str(config.get("pushplus_topic") or "").strip()
    if topic:
        payload["topic"] = topic
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(PUSHPLUS_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("code") == 200:
        print("[PushPlus] 推送成功")
        return True
    print("[PushPlus] 推送失败: %s" % (result.get("msg") or result))
    return False


def send_pushplus_chunks(
    token: str,
    title: str,
    data: dict[str, Any],
    top_n: int,
    per_segment: int,
    config: dict[str, Any] | None = None,
    chunk_limit: int = 90000,
) -> bool:
    results = data.get("results") or []
    sections: list[tuple[str, list[dict[str, Any]]]] = []
    sections.append((f"性价比 Top {top_n}", results[:top_n]))
    sections.append((f"总分 Top {top_n}", sorted(results, key=lambda item: item.get("total_score", 0), reverse=True)[:top_n]))
    for name, accounts in (data.get("segments") or {}).items():
        sections.append((f"{name} 元性价比 Top {per_segment}", (accounts or [])[:per_segment]))

    chunks: list[list[tuple[str, list[dict[str, Any]]]]] = []
    current: list[tuple[str, list[dict[str, Any]]]] = []
    for item in sections:
        candidate = [*current, item]
        content = format_chunk_message(data, title, candidate)
        if current and len(content.encode("utf-8")) > chunk_limit:
            chunks.append(current)
            current = [item]
        else:
            current = candidate
    if current:
        chunks.append(current)

    ok = True
    total = len(chunks)
    for index, chunk_sections in enumerate(chunks, 1):
        heading = f"{title} ({index}/{total})"
        content = format_chunk_message(data, heading, chunk_sections)
        ok = send_pushplus(token, heading, content, config=config) and ok
        time.sleep(0.6)
    return ok


def run(input_path: Path, preview_path: Path, top_n: int, per_segment: int, dry_run: bool) -> bool:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    content = format_message(data, top_n=top_n, per_segment=per_segment)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(content, encoding="utf-8")
    print(f"推送预览已写入: {preview_path}")
    if dry_run:
        return True
    config = load_config()
    token = str(config.get("pushplus_token") or "").strip()
    if not token:
        raise RuntimeError("pushplus_token 未配置")
    title = str(config.get("pushplus_title") or "螃蟹鸣潮账号最终评分 - Top推荐").strip()
    if send_pushplus(token, title, content, config=config):
        return True
    if len(content.encode("utf-8")) > 90000:
        print("[PushPlus] 内容较长，改为分段推送")
        return send_pushplus_chunks(token, title, data, top_n=top_n, per_segment=per_segment, config=config)
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--per-segment", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        ok = run(args.input, args.preview, args.top_n, args.per_segment, args.dry_run)
    except Exception as exc:
        print(f"[ERROR] 推送失败: {exc}")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
