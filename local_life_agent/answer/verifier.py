"""Answer verifier for the single-shop multi-facet flow."""

from __future__ import annotations

import re
from typing import Any

from ..tools.mock_tools import _all_shops


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _match_any_phrase(text: str, phrases: list[str]) -> bool:
    return any(phrase and phrase in text for phrase in phrases)


def _match_any_regex(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _known_shop_names_in_answer(answer: str) -> list[str]:
    matches: list[str] = []
    for shop in _all_shops():
        name = shop.get("shop_name", "")
        if isinstance(name, str) and name and name in answer:
            matches.append(name)
    return matches


def _extract_facet_results(evidence: dict[str, Any], task_type: str) -> list[dict[str, Any]]:
    facet_results = evidence.get("facet_results") or []
    if not facet_results:
        snapshot = evidence.get("ranking_snapshot") or {}
        facet_results = snapshot.get("facet_results") or []
    if facet_results:
        return [item if isinstance(item, dict) else {} for item in facet_results]
    if task_type == "coupon_query":
        return [{"facet": "coupon", "required": True, "status": snapshot.get("status", "unknown")}]
    return []


def _facet_status_text(facet: str, item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("result_status") or "unknown")


def _facet_required(item: dict[str, Any]) -> bool:
    return bool(item.get("required", True))


def _facet_rules(answer: str, facet: str, item: dict[str, Any], issues: list[str]) -> None:
    status = _facet_status_text(facet, item)
    if facet == "coupon":
        if status == "ok":
            if not _match_any_phrase(answer, ["有券", "可用券", "优惠券"]):
                issues.append("coupon_status_missing_positive_claim")
        elif status == "empty":
            if _match_any_regex(answer, [r"(?<!没)有券", r"有可用券", r"有优惠券"]):
                issues.append("coupon_status_false_positive")
            if not _match_any_phrase(answer, ["暂无可用券", "没有券", "当前暂无可用券"]):
                issues.append("coupon_status_missing_empty_notice")
        elif status == "unknown":
            if _match_any_regex(answer, [r"(?<!没)有券", r"有可用券", r"有优惠券", r"暂无可用券"]):
                issues.append("unknown_claimed_as_empty_or_available")
            if not _match_any_phrase(answer, ["暂时无法确认优惠券情况", "获取优惠券信息失败", "稍后再试"]):
                issues.append("unknown_needs_uncertain_notice")
        elif status == "failed":
            if not _match_any_phrase(answer, ["获取优惠券信息失败", "建议稍后再试", "暂时无法确认优惠券情况"]):
                issues.append("failed_needs_failure_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["服务暂时不可用", "稍后再试"]):
                issues.append("circuit_open_needs_unavailable_notice")
        return

    if facet == "open_status":
        open_status = str(
            item.get("open_status")
            or item.get("value")
            or ""
        ).lower()
        if status == "ok":
            if open_status == "open":
                if not _match_any_phrase(answer, ["营业中", "正在营业", "正常营业"]):
                    issues.append("open_status_missing_open_claim")
            elif open_status == "closed":
                if not _match_any_phrase(answer, ["已打烊", "已关门", "不营业"]):
                    issues.append("open_status_missing_closed_claim")
            else:
                if not _match_any_phrase(answer, ["营业状态未知", "暂时无法确认营业状态"]):
                    issues.append("open_status_missing_unknown_notice")
        elif status in {"unknown", "failed"}:
            if _match_any_phrase(answer, ["营业中", "正在营业", "正常营业", "已打烊", "已关门", "不营业"]):
                issues.append("open_status_false_positive")
            if not _match_any_phrase(answer, ["无法确认营业状态", "营业状态暂时无法确认", "获取营业状态失败", "稍后再试"]):
                issues.append("open_status_needs_uncertain_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["服务暂时不可用", "稍后再试"]):
                issues.append("open_status_needs_unavailable_notice")
        return

    if facet == "distance":
        distance_value = item.get("value")
        distance_km = item.get("distance_km")
        eta_minutes = item.get("eta_minutes")
        if isinstance(distance_value, dict):
            distance_km = distance_value.get("distance_km", distance_km)
            eta_minutes = distance_value.get("eta_minutes", eta_minutes)
        elif isinstance(distance_value, (int, float)):
            distance_km = distance_value
        if status == "ok":
            if distance_km is not None:
                expected = str(distance_km)
                if expected not in answer and not _match_any_regex(answer, [r"\d+(\.\d+)?\s*(公里|km|米)"]):
                    issues.append("distance_missing_numeric_claim")
        elif status in {"unknown", "failed"}:
            if _match_any_regex(answer, [r"很近", r"不远", r"很远", r"\d+\s*分钟", r"几分钟"]):
                issues.append("distance_false_positive")
            if not _match_any_phrase(answer, ["无法确认距离", "距离暂时无法确认", "获取距离信息失败", "稍后再试"]):
                issues.append("distance_needs_uncertain_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["服务暂时不可用", "稍后再试"]):
                issues.append("distance_needs_unavailable_notice")


def _extract_ranked_shop_names(evidence: dict[str, Any]) -> list[str]:
    snapshot = evidence.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or snapshot.get("shops") or []
    shop_names: list[str] = []
    for item in ranked:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = (
                item.get("shop_name")
                or item.get("name")
                or item.get("shop_id")
                or ""
            )
            if isinstance(name, str):
                name = name.strip()
        else:
            name = str(item).strip()
        if name:
            shop_names.append(name)
    return shop_names


def _extract_mentioned_order(answer: str, expected_names: list[str]) -> list[str]:
    mentions: list[tuple[int, str]] = []
    for name in expected_names:
        idx = answer.find(name)
        if idx >= 0:
            mentions.append((idx, name))
    mentions.sort(key=lambda item: item[0])
    return [name for _, name in mentions]


def _build_suggested_fix(issues: list[str]) -> str:
    parts: list[str] = []
    if any(issue == "ranking_changed_by_llm" for issue in issues):
        parts.append("请严格按 evidence.ranking_snapshot 的顺序输出，不要重排候选店。")
    if any(issue.startswith("forbidden_claim:") for issue in issues):
        parts.append("删除未被 evidence 支持的断言，只保留可验证事实。")
    if not parts:
        parts.append("请只输出 evidence 支持的内容。")
    return "".join(parts)


def verify_answer(answer: str, evidence: dict, task_type: str) -> dict:
    """Verify an answer against its evidence base."""
    evidence_dict = _to_dict(evidence)
    issues: list[str] = []

    forbidden_claims = evidence_dict.get("forbidden_claims") or []
    for claim in forbidden_claims:
        if isinstance(claim, str) and claim and claim in answer:
            issues.append(f"forbidden_claim:{claim}")

    allowed_shop_names = {
        name for name in (
            item.get("shop_name", "") if isinstance(item, dict) else ""
            for item in (evidence_dict.get("evidence_items") or []) + (evidence_dict.get("unknown_items") or [])
        )
        if isinstance(name, str) and name.strip()
    }
    for name in _known_shop_names_in_answer(answer):
        if allowed_shop_names and name not in allowed_shop_names:
            issues.append(f"shop_mismatch:{name}")

    facet_results = _extract_facet_results(evidence_dict, task_type)
    for item in facet_results:
        facet = str(item.get("facet", ""))
        if not facet:
            continue
        if _facet_required(item):
            _facet_rules(answer, facet, item, issues)

    expected_names = _extract_ranked_shop_names(evidence_dict)
    if len(expected_names) >= 2:
        mentioned_order = _extract_mentioned_order(answer, expected_names)
        if len(mentioned_order) >= 2 and mentioned_order != expected_names[: len(mentioned_order)]:
            issues.append("ranking_changed_by_llm")

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "suggested_fix": "" if passed else _build_suggested_fix(issues),
        "task_type": task_type,
    }
