"""Score normalized Wuthering Waves accounts."""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import sys
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = app_dir()
DEFAULT_INPUT = SCRIPT_DIR / "data" / "sample_detail.json"
DEFAULT_RULES = SCRIPT_DIR / "configs" / "scoring_rules.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "score_results.json"
DEFAULT_CHARACTER_TIERS = SCRIPT_DIR / "configs" / "character_tiers.json"
DEFAULT_TEAM_RULES = SCRIPT_DIR / "configs" / "team_first_examples.json"

RESONANCE_SCORE_POINTS = {
    1: 0.5,
    2: 1.5,
    3: 2.5,
    4: 2.8,
    5: 3.0,
    6: 4.0,
}
TEAM_COMPLETE_BONUS = 0.3
PULLS_PER_TARGET_CHARACTER = 71
POINTS_PER_TARGET_CHARACTER = 2
ASTRITE_PER_PULL = 160
LUNITE_PER_RMB = 20
SIGNATURE_WEAPON_FIRST_POINTS = 0.7
SIGNATURE_WEAPON_EXTRA_POINTS = 0.2

COLLECTIBLE_VALUE_RULES = {
    "服饰": {
        "叱妖诰": {"score": 0.0, "reason": "不计分"},
        "呢绒梦": {"lunite": 2480},
        "城市午茶": {"lunite": 2480},
        "桂枝宁芙": {"lunite": 2480},
        "桃夭灼灼": {"lunite": 3280},
    },
    "摩托饰品": {
        "小小救世主": {"score": 0.0, "reason": "摩托饰品不计分"},
        "绯雪团子": {"score": 0.0, "reason": "摩托饰品不计分"},
    },
    "涂装": {
        "深空与歌者": {"score": 0.0, "reason": "累充奖励，暂不折价计分"},
        "眺望境界之线": {"rmb": 68},
        "若以月为因果": {"rmb": 68},
        "隧者与少女": {"rmb": 168},
        "雪月花": {"rmb": 168},
    },
    "车架模组": {
        "远航星": {"rmb": 168},
        "霁": {"rmb": 168},
    },
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def saturation(raw: float, cap: float, unit: float) -> float:
    if raw <= 0:
        return 0.0
    return cap * (1 - math.exp(-raw / unit))


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def formula_section(rules: dict[str, Any], name: str) -> dict[str, Any]:
    return (rules.get("formula") or {}).get(name) or {}


def as_float_config(data: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=4)
def load_character_tiers(path_text: str = str(DEFAULT_CHARACTER_TIERS)) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {"tier_multipliers": {}, "characters": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    multipliers = data.get("tier_multipliers") or {}
    characters: dict[str, dict[str, Any]] = {}
    for tier, entries in (data.get("tiers") or {}).items():
        multiplier = float(multipliers.get(tier, 0))
        for entry in entries or []:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            characters[name] = {
                "tier": tier,
                "multiplier": multiplier,
                "version": entry.get("version"),
                "role_type": entry.get("role_type"),
                "signature_weapon": entry.get("signature_weapon"),
            }
    return {"tier_multipliers": multipliers, "characters": characters}


@lru_cache(maxsize=4)
def load_team_rules(path_text: str = str(DEFAULT_TEAM_RULES)) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {"teams": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def signature_weapon_points(
    total_refinement: int,
    first_points: float = SIGNATURE_WEAPON_FIRST_POINTS,
    extra_points: float = SIGNATURE_WEAPON_EXTRA_POINTS,
) -> float:
    if total_refinement <= 0:
        return 0.0
    return first_points + (total_refinement - 1) * extra_points


def weapon_refinement_totals(weapons: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for weapon in weapons:
        name = str(weapon.get("name") or "").strip()
        if not name:
            continue
        refinement = max(as_int(weapon.get("refinement"), 1), 1)
        totals[name] = totals.get(name, 0) + refinement
    return totals


def best_character_resonance(characters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for character in characters:
        name = str(character.get("name") or "").strip()
        if not name:
            continue
        resonance = as_int(character.get("resonance"), 0)
        if name not in best or resonance > as_int(best[name].get("resonance"), 0):
            best[name] = dict(character, name=name, resonance=resonance)
    return best


def owned_scored_signature_weapon_names(account: dict[str, Any]) -> set[str]:
    tier_characters = load_character_tiers()["characters"]
    owned = best_character_resonance(account.get("characters") or [])
    names: set[str] = set()
    for character_name in owned:
        tier_info = tier_characters.get(character_name)
        if not tier_info:
            continue
        weapon_name = str(tier_info.get("signature_weapon") or "").strip()
        if weapon_name and weapon_name != "待补充":
            names.add(weapon_name)
    return names


def team_state(character_name: str, owned_names: set[str], team_rules: dict[str, Any]) -> dict[str, Any]:
    rule = (team_rules.get("teams") or {}).get(character_name) or {}
    check_type = rule.get("check_type") or "none"
    matched_team: list[str] = []
    flag = 0

    if check_type == "owned_only":
        flag = 1 if character_name in owned_names else 0
        matched_team = [character_name] if flag else []
    elif check_type == "fixed_team":
        core_team = [str(name).strip() for name in (rule.get("core_team") or []) if str(name).strip()]
        flag = 1 if core_team and all(name in owned_names for name in core_team) else 0
        matched_team = core_team if flag else []
    elif check_type == "two_team":
        for core_team in rule.get("core_teams") or []:
            candidate = [str(name).strip() for name in (core_team or []) if str(name).strip()]
            if candidate and all(name in owned_names for name in candidate):
                flag = 1
                matched_team = candidate
                break

    return {
        "flag": flag,
        "check_type": check_type,
        "position": rule.get("position"),
        "matched_team": matched_team,
        "note": rule.get("note"),
    }


def unique_team_groups(role_details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = []
    seen = set()
    for detail in role_details:
        if not detail.get("team_flag"):
            continue
        members = [name for name in detail.get("matched_team") or [] if name]
        if not members:
            continue
        key = tuple(sorted(members))
        if key in seen:
            continue
        seen.add(key)
        groups.append(
            {
                "anchor": detail.get("name"),
                "check_type": detail.get("team_check_type"),
                "members": members,
                "position": detail.get("team_position"),
                "note": detail.get("team_note"),
            }
        )
    return groups


def score_characters(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules["components"]["character"]
    formula = formula_section(rules, "character")
    resonance_points = {
        int(key): float(value)
        for key, value in (formula.get("resonance_points") or RESONANCE_SCORE_POINTS).items()
    }
    team_complete_bonus = as_float_config(formula, "team_complete_bonus", TEAM_COMPLETE_BONUS)
    signature_first = as_float_config(formula, "signature_weapon_first_points", SIGNATURE_WEAPON_FIRST_POINTS)
    signature_extra = as_float_config(formula, "signature_weapon_extra_points", SIGNATURE_WEAPON_EXTRA_POINTS)
    characters = account.get("characters") or []
    weapons = account.get("weapons") or []
    important = set(account.get("main_important_keys") or [])
    tier_rules = load_character_tiers()
    tier_characters = tier_rules["characters"]
    team_rules = load_team_rules()
    character_by_name = best_character_resonance(characters)
    owned_names = set(character_by_name)
    weapon_totals = weapon_refinement_totals(weapons)

    role_details = []
    character_score = 0.0
    resonance_score = 0.0
    signature_score = 0.0
    team_bonus_score = 0.0

    for name, character in character_by_name.items():
        tier_info = tier_characters.get(name)
        if not tier_info:
            continue
        multiplier = float(tier_info.get("multiplier") or 0)
        resonance = as_int(character.get("resonance"), 0)
        resonance_part = resonance_points.get(resonance, 0.0)
        signature_weapon = str(tier_info.get("signature_weapon") or "").strip()
        signature_refinement = weapon_totals.get(signature_weapon, 0)
        signature_part = signature_weapon_points(signature_refinement, signature_first, signature_extra)
        team = team_state(name, owned_names, team_rules)
        team_bonus = team_complete_bonus if team["flag"] else 0.0
        raw_multiplier = 1 + resonance_part + signature_part + team_bonus
        role_score = multiplier * raw_multiplier
        resonance_score += resonance_part
        signature_score += signature_part
        team_bonus_score += multiplier * team_bonus
        character_score += role_score
        role_details.append(
            {
                "name": name,
                "tier": tier_info.get("tier"),
                "tier_multiplier": multiplier,
                "version": tier_info.get("version"),
                "role_type": tier_info.get("role_type"),
                "resonance": resonance,
                "resonance_score": round(resonance_part, 2),
                "signature_weapon": signature_weapon,
                "signature_refinement_total": signature_refinement,
                "signature_weapon_score": round(signature_part, 2),
                "team_flag": int(team["flag"]),
                "team_bonus": team_bonus,
                "team_score_contribution": round(multiplier * team_bonus, 2),
                "team_check_type": team["check_type"],
                "team_position": team.get("position"),
                "matched_team": team["matched_team"],
                "team_note": team.get("note"),
                "score": round(role_score, 2),
            }
        )

    role_details.sort(key=lambda item: item["score"], reverse=True)
    important_hits = [name for name in character_by_name if name in important]
    yellow_count = float(account.get("yellow_count") or 0)
    yellow_score = 0.0
    score = character_score
    return {
        "score": round(score, 2),
        "max": cfg["max"],
        "count": len(characters),
        "scored_limited_count": len(role_details),
        "five_star_character_count": account.get("five_star_character_count"),
        "count_score": 0.0,
        "formula_score": round(character_score, 2),
        "resonance_score": round(resonance_score, 2),
        "signature_weapon_score": round(signature_score, 2),
        "team_bonus_score": round(team_bonus_score, 2),
        "important_score": 0.0,
        "yellow_count": int(yellow_count),
        "yellow_score": round(yellow_score, 2),
        "important_hits": important_hits,
        "role_details": role_details,
        "completed_team_groups": unique_team_groups(role_details),
    }


def score_weapons(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules["components"]["weapon"]
    all_weapons = account.get("weapons") or []
    excluded_signature_names = owned_scored_signature_weapon_names(account)
    weapons = [
        weapon for weapon in all_weapons
        if str(weapon.get("name") or "").strip() not in excluded_signature_names
    ]
    excluded_weapons = [
        weapon for weapon in all_weapons
        if str(weapon.get("name") or "").strip() in excluded_signature_names
    ]
    excluded_present_names = {
        str(weapon.get("name") or "").strip()
        for weapon in excluded_weapons
        if str(weapon.get("name") or "").strip()
    }
    count_score = saturation(len(weapons), cfg["count_cap"], cfg["count_curve_unit"])
    refinement_points = cfg["refinement_points"]
    refinement_raw = 0.0
    for weapon in weapons:
        refinement = str(weapon.get("refinement") or 0)
        refinement_raw += float(refinement_points.get(refinement, 0))
    refinement_score = clamp(refinement_raw, 0, cfg["refinement_cap"])
    structured_groups = account.get("refinement_groups") or {}
    scored_structured_groups = {
        name: values
        for name, values in structured_groups.items()
        if str(name).strip() not in excluded_signature_names
    }
    structured_count = sum(len(values) for values in scored_structured_groups.values())
    structured_score = clamp(structured_count * 0.25, 0, cfg["structured_refinement_cap"])
    score = count_score + refinement_score + structured_score
    return {
        "score": round(clamp(score, 0, cfg["max"]), 2),
        "max": cfg["max"],
        "count": len(all_weapons),
        "scored_count": len(weapons),
        "excluded_signature_count": len(excluded_weapons),
        "excluded_signature_weapon_names": sorted(excluded_present_names),
        "owned_signature_weapon_names": sorted(excluded_signature_names),
        "count_score": round(count_score, 2),
        "refinement_score": round(refinement_score, 2),
        "structured_refinement_count": structured_count,
        "structured_refinement_score": round(structured_score, 2),
    }


def score_resources(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    formula = formula_section(rules, "resource")
    astrite_per_pull = as_float_config(formula, "astrite_per_pull", ASTRITE_PER_PULL)
    lunite_per_pull = as_float_config(formula, "lunite_per_pull", ASTRITE_PER_PULL)
    coral_per_pull = as_float_config(formula, "coral_per_pull", 8.0)
    pulls_per_target = as_float_config(formula, "pulls_per_target_character", PULLS_PER_TARGET_CHARACTER)
    points_per_target = as_float_config(formula, "points_per_target_character", POINTS_PER_TARGET_CHARACTER)
    resources = account.get("resources") or {}
    astrite = float(resources.get("星声") or 0)
    lunite = float(resources.get("月相") or 0)
    coral = float(resources.get("余波珊瑚") or 0)
    golden_wave = float(resources.get("浮金波纹") or 0)
    weapon_wave = float(resources.get("铸潮波纹") or 0)

    pulls_from_astrite = astrite / max(astrite_per_pull, 1.0)
    pulls_from_lunite = lunite / max(lunite_per_pull, 1.0)
    pulls_from_coral = coral / max(coral_per_pull, 1.0)
    pulls_from_golden_wave = golden_wave
    pulls = pulls_from_astrite + pulls_from_lunite + pulls_from_coral + pulls_from_golden_wave
    score = pulls / max(pulls_per_target, 1.0) * points_per_target
    return {
        "score": round(score, 2),
        "max": None,
        "scoring_method": f"抽卡资源分：星声/月相/浮金波纹/余波珊瑚折算限定角色池等效抽数；铸潮波纹不计分；{pulls_per_target:g}抽={points_per_target:g}分。",
        "estimated_pulls": round(pulls, 1),
        "pull_score": round(score, 2),
        "extra_score": 0.0,
        "pull_breakdown": {
            "星声": round(pulls_from_astrite, 2),
            "月相": round(pulls_from_lunite, 2),
            "浮金波纹": round(pulls_from_golden_wave, 2),
            "余波珊瑚": round(pulls_from_coral, 2),
            "铸潮波纹": 0.0,
        },
        "ignored": {
            "铸潮波纹": weapon_wave,
        },
    }


def score_risk(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules["components"]["risk"]
    flags = account.get("risk_flags") or {}
    deductions = []
    score = float(cfg["base"])
    dcfg = cfg["deductions"]

    if "已绑定" in str(flags.get("tap_binding") or ""):
        score -= dcfg["tap_bound"]
        deductions.append("TAP 已绑定")
    if "已绑" in str(flags.get("wegame_binding") or ""):
        score -= dcfg["wegame_bound"]
        deductions.append("Wegame 已绑定")
    cd = str(flags.get("change_bind_cd") or "")
    if cd and "无" not in cd:
        score -= dcfg["change_bind_cd"]
        deductions.append("存在换绑 CD")
    if flags.get("screenshot_source") == "自主截图":
        score -= dcfg["self_screenshot"]
        deductions.append("自主截图")
    if not flags.get("guarantee"):
        score -= dcfg["no_guarantee"]
        deductions.append("未识别到找回包赔")

    return {
        "score": round(clamp(score, 0, cfg["max"]), 2),
        "max": cfg["max"],
        "deductions": deductions,
    }


def collectible_rule_to_score(
    category: str,
    name: str,
    formula: dict[str, Any] | None = None,
) -> dict[str, Any]:
    formula = formula or {}
    rule = (COLLECTIBLE_VALUE_RULES.get(category) or {}).get(name) or {}
    if "score" in rule:
        return {
            "name": name,
            "category": category,
            "score": round(float(rule.get("score") or 0), 2),
            "equivalent_lunite": 0.0,
            "equivalent_pulls": 0.0,
            "source": rule.get("reason") or "手动不计分",
        }

    equivalent_lunite = 0.0
    source = "未配置价格，暂不计分"
    if "lunite" in rule:
        equivalent_lunite = float(rule["lunite"])
        source = f"{int(equivalent_lunite)}月相"
    elif "rmb" in rule:
        lunite_per_rmb = as_float_config(formula, "lunite_per_rmb", LUNITE_PER_RMB)
        equivalent_lunite = float(rule["rmb"]) * lunite_per_rmb
        source = f"{rule['rmb']}元 * {lunite_per_rmb:g} = {int(equivalent_lunite)}月相"

    astrite_per_pull = as_float_config(formula, "astrite_per_pull", ASTRITE_PER_PULL)
    pulls_per_target = as_float_config(formula, "pulls_per_target_character", PULLS_PER_TARGET_CHARACTER)
    points_per_target = as_float_config(formula, "points_per_target_character", POINTS_PER_TARGET_CHARACTER)
    equivalent_pulls = equivalent_lunite / max(astrite_per_pull, 1.0)
    score = equivalent_pulls / max(pulls_per_target, 1.0) * points_per_target
    return {
        "name": name,
        "category": category,
        "score": round(score, 2),
        "equivalent_lunite": round(equivalent_lunite, 2),
        "equivalent_pulls": round(equivalent_pulls, 2),
        "source": source,
    }


def score_collectibles(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    formula = formula_section(rules, "collectible")
    pulls_per_target = as_float_config(formula, "pulls_per_target_character", PULLS_PER_TARGET_CHARACTER)
    points_per_target = as_float_config(formula, "points_per_target_character", POINTS_PER_TARGET_CHARACTER)
    data = account.get("collectibles") or {}
    fashion = len(data.get("服饰") or [])
    motor = len(data.get("摩托饰品") or [])
    paint = len(data.get("涂装") or [])
    frame = len(data.get("车架模组") or [])
    items = []
    for category in ("服饰", "摩托饰品", "涂装", "车架模组"):
        for name in data.get(category) or []:
            items.append(collectible_rule_to_score(category, str(name), formula))
    raw = sum(float(item["score"]) for item in items)
    return {
        "score": round(raw, 2),
        "max": None,
        "scoring_method": f"饰品分数：月相价或人民币价折算为月相，再折算抽数；{pulls_per_target:g}抽={points_per_target:g}分。叱妖诰与摩托饰品不计分。",
        "fashion_count": fashion,
        "motor_count": motor,
        "paint_count": paint,
        "frame_mod_count": frame,
        "detail": data,
        "items": items,
    }


def score_trade(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules["components"]["trade"]
    trade = account.get("trade") or {}
    score = float(cfg["base"])
    detail = []
    if trade.get("agree_bargain"):
        score += float(cfg["bargain_bonus"])
        detail.append("支持议价")
    published_text = str(account.get("published_text") or "")
    if "分钟" in published_text or "小时" in published_text:
        score += float(cfg["fresh_bonus"])
        detail.append("新近上架")
    hot_count = trade.get("hot_count") or 0
    try:
        hot_count = int(hot_count)
    except (TypeError, ValueError):
        hot_count = 0
    if hot_count >= int(cfg["hot_penalty_threshold"]):
        score -= float(cfg["hot_penalty"])
        detail.append("热度较高")
    return {
        "score": round(clamp(score, 0, cfg["max"]), 2),
        "max": cfg["max"],
        "detail": detail,
        "agree_bargain": trade.get("agree_bargain"),
        "bargain_status": trade.get("bargain_status"),
        "bargain_price": trade.get("bargain_price"),
        "hot_count": hot_count,
        "collect_count": trade.get("collect_count"),
    }


def recommendation_reasons(account: dict[str, Any], parts: dict[str, Any]) -> list[str]:
    reasons = []
    char = parts["character"]
    weapon = parts["weapon"]
    resource = parts["resource"]
    collectible = parts.get("collectible", {})
    if char["count"] >= 15:
        reasons.append(f"五星角色多：{char['count']} 个")
    if char["important_hits"]:
        reasons.append("重点角色：" + "、".join(char["important_hits"][:4]))
    if weapon["count"] >= 8:
        reasons.append(f"五星武器多：{weapon['count']} 把")
    if resource["estimated_pulls"] >= 50:
        reasons.append(f"可折算抽数约 {resource['estimated_pulls']}")
    if collectible.get("score", 0) >= 2:
        reasons.append(
            "收藏项：服饰%d/摩托%d/涂装%d/车架%d"
            % (
                collectible.get("fashion_count", 0),
                collectible.get("motor_count", 0),
                collectible.get("paint_count", 0),
                collectible.get("frame_mod_count", 0),
            )
        )
    return reasons


def total_scored_components(parts: dict[str, Any]) -> float:
    """Trade and risk are retained for review, but not included in scoring."""

    scored_component_names = ("character", "weapon", "resource", "collectible")
    return sum(float(parts[name]["score"]) for name in scored_component_names)


def is_filtered_server(account: dict[str, Any]) -> bool:
    server = str(account.get("server") or "")
    title = str(account.get("title") or "")
    return "B服" in server or "B服" in title


def score_account(account: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    parts = {
        "character": score_characters(account, rules),
        "weapon": score_weapons(account, rules),
        "resource": score_resources(account, rules),
        "risk": score_risk(account, rules),
        "collectible": score_collectibles(account, rules),
        "trade": score_trade(account, rules),
    }
    total = total_scored_components(parts)
    return {
        "account_id": account.get("account_id"),
        "product_unique_no": account.get("product_unique_no"),
        "price": account.get("price"),
        "detail_url": account.get("detail_url"),
        "title": account.get("title"),
        "server": account.get("server"),
        "level": account.get("level"),
        "total_score": round(total, 2),
        "scored_components": ["character", "weapon", "resource", "collectible"],
        "review_only_components": ["risk", "trade"],
        "component_scores": parts,
        "reasons": recommendation_reasons(account, parts),
        "deductions": parts["risk"]["deductions"],
        "source": account,
    }


def run(input_path: Path, rules_path: Path, output_path: Path) -> dict[str, Any]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    load_character_tiers.cache_clear()
    load_team_rules.cache_clear()
    accounts = data.get("items") or []
    filtered = [account for account in accounts if is_filtered_server(account)]
    scorable_accounts = [account for account in accounts if not is_filtered_server(account)]
    results = [score_account(account, rules) for account in scorable_accounts]
    results.sort(key=lambda item: item["total_score"], reverse=True)
    output = {
        "source": {
            "input": str(input_path),
            "rules": str(rules_path),
            "rules_version": rules.get("version"),
            "filtered_b_server_count": len(filtered),
        },
        "total_accounts": len(results),
        "filtered_accounts": len(filtered),
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.input, args.rules, args.output)
    print(f"Scored {result['total_accounts']} accounts; saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
