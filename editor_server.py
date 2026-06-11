from __future__ import annotations

import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
CHARACTER_TIERS_PATH = ROOT / "configs" / "character_tiers.json"
CHARACTER_TIERS_MD_PATH = ROOT / "角色梯度预设.md"
TEAM_RULES_PATH = ROOT / "configs" / "team_first_examples.json"
TEAM_RULES_MD_PATH = ROOT / "角色第一成型队表.md"


def write_character_tiers_markdown(data: dict) -> None:
    multipliers = data.get("tier_multipliers", {})
    tiers = data.get("tiers", {})
    lines = [
        "# 角色梯度预设",
        "",
        "这版由角色梯度编辑器保存生成。当前仍遵守本项目规则：暂不把常驻五星、四星和漂泊者纳入角色倍率计分。",
        "",
        "后续确认后，会把它接入新的角色计分公式：",
        "",
        "```text",
        "单角色分 = 角色倍率 * (1 + 命座分 + 专武分)",
        "```",
        "",
        "## 梯度倍率",
        "",
        "| 梯度 | 角色倍率 |",
        "| --- | ---: |",
    ]
    for tier, value in multipliers.items():
        lines.append(f"| {tier} | {value} |")

    lines.extend(["", "## 当前预设", "", "| 梯度 | 角色 |", "| --- | --- |"])
    for tier, roles in tiers.items():
        names = "、".join(role.get("name", "") for role in roles) or "暂无计分角色"
        lines.append(f"| {tier} | {names} |")

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本文件由 `配套编辑器保存接口` 自动生成。",
            "- 常驻五星、四星和漂泊者暂不参与本轮角色倍率计分。",
            "- 如果在编辑器中继续调整，请点击“保存到配置文件”同步更新本文件和 JSON 配置。",
            "",
        ]
    )
    CHARACTER_TIERS_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def validate_character_tiers(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象")
    if not isinstance(data.get("tier_multipliers"), dict):
        raise ValueError("缺少 tier_multipliers 对象")
    if not isinstance(data.get("tiers"), dict):
        raise ValueError("缺少 tiers 对象")
    for tier, roles in data["tiers"].items():
        if not isinstance(roles, list):
            raise ValueError(f"{tier} 必须是角色数组")
        for role in roles:
            if not isinstance(role, dict) or not role.get("name"):
                raise ValueError(f"{tier} 中存在缺少 name 的角色")
    return data


def team_condition_text(info: dict) -> str:
    check_type = info.get("check_type")
    if check_type == "owned_only":
        return "拥有即满足"
    if check_type == "two_team":
        teams = info.get("core_teams", [])
        return "；或 ".join(" + ".join(team) for team in teams)
    return " + ".join(info.get("core_team", []))


def check_type_label(check_type: str) -> str:
    return {
        "owned_only": "拥有即满足",
        "fixed_team": "固定配对检测",
        "two_team": "双配对任选",
    }.get(check_type, check_type)


def write_team_rules_markdown(data: dict) -> None:
    lines = [
        "# 鸣潮角色配队完整度表",
        "",
        "这版由配队规则编辑器保存生成。它只服务账号评分，不追求列完所有可用配队。",
        "",
        "## 评分口径",
        "",
        "| 判定方式 | 说明 | 建议加分 |",
        "| --- | --- | ---: |",
        "| 拥有即满足 | 角色本身就是泛用辅助/生存/通用增益，不锁定具体队伍 | +4 |",
        "| 固定配对检测 | 同时拥有 2 个核心角色 | +4 |",
        "| 双配对任选 | 两套核心二人组中任意一套齐全 | +4 |",
        "| 不满足 | 缺核心队友，或角色仅单挂 | +0 |",
        "",
        "3号位不绑定。常驻五星、四星和漂泊者可以作为配对条件出现，但它们本身仍不进入角色倍率计分。",
        "",
        "## 当前表",
        "",
        "| 角色 | 定位 | 判定方式 | 核心配对 / 条件 | 备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, info in data.get("teams", {}).items():
        lines.append(
            f"| {name} | {info.get('position', '')} | "
            f"{check_type_label(info.get('check_type', ''))} | "
            f"{team_condition_text(info)} | {info.get('note', '')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本文件由 `配队规则编辑器` 自动生成。",
            "- `two_team` 的角色满足任意一套核心二人组即可获得完整配队加分。",
            "- 3号位不绑定，泛用辅助/生存位不作为核心条件卡分。",
            "- 如果在编辑器中继续调整，请点击“保存到配置文件”同步更新本文件和 JSON 配置。",
            "",
        ]
    )
    TEAM_RULES_MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def validate_team_rules(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象")
    teams = data.get("teams")
    if not isinstance(teams, dict):
        raise ValueError("缺少 teams 对象")
    for name, info in teams.items():
        if not isinstance(info, dict):
            raise ValueError(f"{name} 必须是对象")
        check_type = info.get("check_type")
        if check_type not in {"owned_only", "fixed_team", "two_team"}:
            raise ValueError(f"{name} 的 check_type 无效")
        if check_type == "owned_only":
            info["core_team"] = []
            info.pop("core_teams", None)
        elif check_type == "fixed_team":
            if not isinstance(info.get("core_team"), list) or not info["core_team"]:
                raise ValueError(f"{name} 的 core_team 必须是非空数组")
            if len(info["core_team"]) != 2:
                raise ValueError(f"{name} 的 core_team 必须正好是 2 个角色")
            info.pop("core_teams", None)
        else:
            core_teams = info.get("core_teams")
            if not isinstance(core_teams, list) or not core_teams:
                raise ValueError(f"{name} 的 core_teams 必须是非空数组")
            if len(core_teams) > 2:
                raise ValueError(f"{name} 的 two_team 最多只能有两套队伍")
            for team in core_teams:
                if not isinstance(team, list) or not team:
                    raise ValueError(f"{name} 的每套队伍都必须是非空数组")
                if len(team) != 2:
                    raise ValueError(f"{name} 的 two_team 每套必须正好是 2 个角色")
            info.pop("core_team", None)
    return data


class EditorHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/character-tiers":
            self.send_json(json.loads(CHARACTER_TIERS_PATH.read_text(encoding="utf-8")))
            return
        if parsed.path == "/api/team-rules":
            self.send_json(json.loads(TEAM_RULES_PATH.read_text(encoding="utf-8")))
            return
        if parsed.path in {"/", ""}:
            self.path = "/角色梯度编辑器.html"
        else:
            self.path = unquote(self.path)
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/character-tiers":
            self.save_character_tiers()
            return
        if parsed.path == "/api/team-rules":
            self.save_team_rules()
            return
        if parsed.path not in {"/api/character-tiers", "/api/team-rules"}:
            self.send_error(404, "Unknown API")
            return

    def save_character_tiers(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = validate_character_tiers(json.loads(raw))
            CHARACTER_TIERS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            write_character_tiers_markdown(data)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self.send_json(
            {
                "ok": True,
                "saved": str(CHARACTER_TIERS_PATH),
                "markdown": str(CHARACTER_TIERS_MD_PATH),
            }
        )

    def save_team_rules(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = validate_team_rules(json.loads(raw))
            TEAM_RULES_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            write_team_rules_markdown(data)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        self.send_json(
            {
                "ok": True,
                "saved": str(TEAM_RULES_PATH),
                "markdown": str(TEAM_RULES_MD_PATH),
            }
        )

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    server = ThreadingHTTPServer(("127.0.0.1", port), EditorHandler)
    print(f"Editor server: http://127.0.0.1:{port}/角色梯度编辑器.html")
    print(f"Tier API:      http://127.0.0.1:{port}/api/character-tiers")
    print(f"Team API:      http://127.0.0.1:{port}/api/team-rules")
    server.serve_forever()


if __name__ == "__main__":
    main()
