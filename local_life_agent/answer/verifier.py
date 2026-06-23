"""Answer verifier for local-life flows."""

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
        snapshot = evidence.get("ranking_snapshot") or {}
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
            if not _match_any_phrase(answer, ["\u6709\u5238", "\u53ef\u7528\u5238", "\u4f18\u60e0\u5238"]):
                issues.append("coupon_status_missing_positive_claim")
        elif status == "empty":
            if _match_any_regex(answer, [r"(?<!\u6ca1)\u6709\u5238", r"\u6709\u53ef\u7528\u5238", r"\u6709\u4f18\u60e0\u5238"]):
                issues.append("coupon_status_false_positive")
            if not _match_any_phrase(answer, ["\u6682\u65e0\u53ef\u7528\u5238", "\u6ca1\u6709\u5238", "\u5f53\u524d\u6682\u65e0\u53ef\u7528\u5238"]):
                issues.append("coupon_status_missing_empty_notice")
        elif status == "unknown":
            if _match_any_regex(answer, [r"(?<!\u6ca1)\u6709\u5238", r"\u6709\u53ef\u7528\u5238", r"\u6709\u4f18\u60e0\u5238", r"\u6682\u65e0\u53ef\u7528\u5238"]):
                issues.append("unknown_claimed_as_empty_or_available")
            if not _match_any_phrase(answer, ["\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u4f18\u60e0\u5238\u60c5\u51b5", "\u83b7\u53d6\u4f18\u60e0\u5238\u4fe1\u606f\u5931\u8d25", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("unknown_needs_uncertain_notice")
        elif status == "failed":
            if not _match_any_phrase(answer, ["\u83b7\u53d6\u4f18\u60e0\u5238\u4fe1\u606f\u5931\u8d25", "\u5efa\u8bae\u7a0d\u540e\u518d\u8bd5", "\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u4f18\u60e0\u5238\u60c5\u51b5"]):
                issues.append("failed_needs_failure_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("circuit_open_needs_unavailable_notice")
        return

    if facet == "open_status":
        open_status = str(item.get("open_status") or item.get("value") or "").lower()
        if status == "ok":
            if open_status == "open":
                if not _match_any_phrase(answer, ["\u8425\u4e1a\u4e2d", "\u6b63\u5728\u8425\u4e1a", "\u6b63\u5e38\u8425\u4e1a"]):
                    issues.append("open_status_missing_open_claim")
            elif open_status == "closed":
                if not _match_any_phrase(answer, ["\u5df2\u6253\u70ca", "\u5df2\u5173\u95e8", "\u4e0d\u8425\u4e1a"]):
                    issues.append("open_status_missing_closed_claim")
            else:
                if not _match_any_phrase(answer, ["\u8425\u4e1a\u72b6\u6001\u672a\u77e5", "\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u8425\u4e1a\u72b6\u6001"]):
                    issues.append("open_status_missing_unknown_notice")
        elif status in {"unknown", "failed"}:
            if _match_any_phrase(answer, ["\u8425\u4e1a\u4e2d", "\u6b63\u5728\u8425\u4e1a", "\u6b63\u5e38\u8425\u4e1a", "\u5df2\u6253\u70ca", "\u5df2\u5173\u95e8", "\u4e0d\u8425\u4e1a"]):
                issues.append("open_status_false_positive")
            if not _match_any_phrase(answer, ["\u65e0\u6cd5\u786e\u8ba4\u8425\u4e1a\u72b6\u6001", "\u8425\u4e1a\u72b6\u6001\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4", "\u83b7\u53d6\u8425\u4e1a\u72b6\u6001\u5931\u8d25", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("open_status_needs_uncertain_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("open_status_needs_unavailable_notice")
        return

    if facet == "distance":
        distance_value = item.get("value")
        distance_km = item.get("distance_km")
        if isinstance(distance_value, dict):
            distance_km = distance_value.get("distance_km", distance_km)
        elif isinstance(distance_value, (int, float)):
            distance_km = distance_value
        if status == "ok":
            if distance_km is not None:
                expected = str(distance_km)
                if expected not in answer and not _match_any_regex(answer, [r"\d+(\.\d+)?\s*(\u516c\u91cc|km|\u7c73)"]):
                    issues.append("distance_missing_numeric_claim")
        elif status in {"unknown", "failed"}:
            if _match_any_regex(answer, [r"\u5f88\u8fd1", r"\u4e0d\u8fdc", r"\u5f88\u8fdc", r"\d+\s*\u5206\u949f", r"\u51e0\u5206\u949f"]):
                issues.append("distance_false_positive")
            if not _match_any_phrase(answer, ["\u65e0\u6cd5\u786e\u8ba4\u8ddd\u79bb", "\u8ddd\u79bb\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4", "\u83b7\u53d6\u8ddd\u79bb\u4fe1\u606f\u5931\u8d25", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("distance_needs_uncertain_notice")
        elif status == "circuit_open":
            if not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("distance_needs_unavailable_notice")


def _extract_ranked_shop_names(evidence: dict[str, Any]) -> list[str]:
    snapshot = evidence.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or snapshot.get("shops") or []
    shop_names: list[str] = []
    for item in ranked:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("shop_name") or item.get("name") or item.get("shop_id") or "").strip()
        else:
            name = str(item).strip()
        if name:
            shop_names.append(name)
    return shop_names


def _extract_mentioned_order(answer: str, expected_names: list[str]) -> list[str]:
    mentions: list[tuple[int, str]] = []
    for name in expected_names:
        index = answer.find(name)
        if index >= 0:
            mentions.append((index, name))
    mentions.sort(key=lambda item: item[0])
    return [name for _, name in mentions]


def _comparison_shop_names(evidence: dict[str, Any]) -> list[str]:
    matrix = evidence.get("comparison_matrix") or {}
    names: list[str] = []
    for row in matrix.get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("shop_name", "")).strip() or str(row.get("shop_id", "")).strip()
        if name:
            names.append(name)
    return names


def _comparison_overall_ranked_names(evidence: dict[str, Any]) -> list[str]:
    matrix = evidence.get("comparison_matrix") or {}
    ranked = matrix.get("overall_ranked") or []
    names: list[str] = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        name = str(item.get("shop_name", "") or item.get("shop_id", "")).strip()
        if name:
            names.append(name)
    return names


def _comparison_issues(answer: str, evidence: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    matrix = evidence.get("comparison_matrix") or {}
    rows = [row for row in (matrix.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return issues

    allowed_shop_names = set(_comparison_shop_names(evidence))
    for name in _known_shop_names_in_answer(answer):
        if allowed_shop_names and name not in allowed_shop_names:
            issues.append(f"shop_mismatch:{name}")

    mentioned_allowed_shops = [name for name in allowed_shop_names if name and name in answer]
    if _match_any_phrase(answer, ["\u66f4\u597d", "\u66f4\u4f18", "\u80dc\u51fa", "\u9886\u5148"]) and not mentioned_allowed_shops:
        issues.append("shop_not_in_matrix")

    if any(row.get("coupon_status") == "unknown" for row in rows) and _match_any_phrase(answer, ["\u66f4\u5dee", "\u4e0d\u5982", "\u66f4\u5f31", "\u66f4\u5c11"]):
        issues.append("unknown_claimed_as_worse")
    if any(str(row.get("open_status", "")).lower() == "unknown" for row in rows) and _match_any_phrase(answer, ["\u66f4\u5dee", "\u4e0d\u5982", "\u66f4\u5f31", "\u66f4\u5c11"]):
        issues.append("unknown_claimed_as_worse")
    if any(row.get("distance_km") is None for row in rows) and _match_any_phrase(answer, ["\u66f4\u5dee", "\u4e0d\u5982", "\u66f4\u5f31", "\u66f4\u5c11"]):
        issues.append("unknown_claimed_as_worse")

    dimension_winners = matrix.get("dimension_winners") or {}
    if _match_any_phrase(answer, ["\u4f18\u60e0", "\u6709\u5238", "\u5238"]) and "coupon" not in dimension_winners:
        issues.append("unprovided_dimension_winner")
    if _match_any_phrase(answer, ["\u8425\u4e1a", "\u5f00\u95e8"]) and "open_status" not in dimension_winners:
        issues.append("unprovided_dimension_winner")
    if _match_any_phrase(answer, ["\u8ddd\u79bb", "\u66f4\u8fd1", "\u8fd1\u4e00\u70b9"]) and "distance" not in dimension_winners:
        issues.append("unprovided_dimension_winner")
    if _match_any_phrase(answer, ["\u8bc4\u5206", "\u53e3\u7891", "\u8bc4\u4ef7"]) and "rating" not in dimension_winners:
        issues.append("unprovided_dimension_winner")

    expected_names = _comparison_overall_ranked_names(evidence) or _extract_ranked_shop_names(evidence)
    if len(expected_names) >= 2 and _match_any_phrase(answer, ["\u66f4\u597d", "\u66f4\u4f18", "\u9886\u5148", "\u80dc\u51fa", "\u66f4\u5360\u4f18"]) and not _match_any_phrase(
        answer,
        ["\u4e0d\u80fd\u5224\u65ad\u8c01\u66f4\u597d", "\u65e0\u6cd5\u5224\u65ad\u8c01\u66f4\u597d", "\u6682\u65f6\u4e0d\u80fd\u5224\u65ad\u8c01\u66f4\u597d"],
    ):
        mentioned_ranked = [name for name in expected_names if name and name in answer]
        if mentioned_ranked:
            if mentioned_ranked[0] != expected_names[0]:
                issues.append("ranking_changed_by_llm")
        else:
            mentioned_order = _extract_mentioned_order(answer, expected_names)
            if mentioned_order and mentioned_order[0] != expected_names[0]:
                issues.append("ranking_changed_by_llm")

    return issues


def _build_suggested_fix(issues: list[str]) -> str:
    parts: list[str] = []
    if any(issue in {"ranking_changed_by_llm", "ranking_changed"} for issue in issues):
        parts.append("\u8bf7\u4e25\u683c\u6309 evidence \u4e2d\u7684\u6392\u5e8f\u8f93\u51fa\uff0c\u4e0d\u8981\u91cd\u6392\u5019\u9009\u5e97\u3002")
    if any(issue in {"unknown_claimed_as_worse", "unknown_as_false"} for issue in issues):
        parts.append("\u4e0d\u8981\u628a unknown \u4fe1\u606f\u8bf4\u6210\u66f4\u5dee\u6216\u66f4\u5f31\uff0c\u53ea\u80fd\u8bf4\u660e\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u3002")
    if any(issue in {"shop_not_in_matrix", "hallucinated_shop_name", "shop_mismatch"} or any(issue.startswith("shop_mismatch:") for issue in issues) for issue in issues):
        parts.append("\u53ea\u80fd\u6bd4\u8f83 evidence \u77e9\u9635\u91cc\u51fa\u73b0\u7684\u5e97\u94fa\u3002")
    if any(issue in {"unprovided_dimension_winner", "unsupported_comparison_winner", "comparison_matrix_mismatch"} for issue in issues):
        parts.append("\u4e0d\u8981\u58f0\u79f0\u672a\u5728 comparison_matrix.dimension_winners \u91cc\u63d0\u4f9b\u7684\u7ef4\u5ea6\u80dc\u51fa\u3002")
    if any(issue.startswith("forbidden_claim:") or "forbidden_claim" in issue for issue in issues):
        parts.append("\u5220\u9664\u672a\u88ab evidence \u652f\u6301\u7684\u65ad\u8a00\uff0c\u53ea\u4fdd\u7559\u53ef\u9a8c\u8bc1\u4e8b\u5b9e\u3002")
    if any("unsupported_" in issue or "tool_failure" in issue or "empty_result" in issue for issue in issues):
        parts.append("\u4e0d\u8981\u7f16\u9020\u6216\u4f7f\u7528\u672a\u88ab evidence \u652f\u6301\u7684\u4fe1\u606f\u3002")
    if not parts:
        parts.append("\u8bf7\u53ea\u8f93\u51fa evidence \u652f\u6301\u7684\u5185\u5bb9\u3002")
    return "".join(parts)


def verify_answer(answer: str, evidence: dict, task_type: str) -> dict:
    """Verify an answer against its evidence base."""
    evidence_dict = _to_dict(evidence)
    issues: list[str] = []

    # A. Run B2MiniVerifier checks
    from .b2_mini_verifier import B2MiniVerifier
    from .generator import _build_decision_plan
    
    mock_answer_plan = {
        "answer_type": task_type,
        "forbidden_claims": evidence_dict.get("forbidden_claims") or [],
        "must_mention_unknowns": [
            item.get("shop_name", "") if isinstance(item, dict) else str(item)
            for item in (evidence_dict.get("unknown_items") or [])
            if (item.get("shop_name", "") if isinstance(item, dict) else str(item))
        ]
    }
    plan = _build_decision_plan(mock_answer_plan, evidence_dict)
    
    verifier = B2MiniVerifier()
    res = verifier.verify(plan, answer)
    if not res["passed"]:
        for v in res["violations"]:
            if v not in issues:
                issues.append(v)

    # B. Legacy check rules (to preserve existing test behaviors)
    forbidden_claims = evidence_dict.get("forbidden_claims") or []
    for claim in forbidden_claims:
        if isinstance(claim, str) and claim and claim in answer:
            if f"forbidden_claim:{claim}" not in issues:
                issues.append(f"forbidden_claim:{claim}")

    if task_type == "comparison" or (evidence_dict.get("comparison_matrix") or {}).get("rows"):
        issues.extend(_comparison_issues(answer, evidence_dict))
        # Deduplicate
        unique_issues = []
        for issue in issues:
            if issue not in unique_issues:
                unique_issues.append(issue)
        passed = len(unique_issues) == 0
        return {
            "passed": passed,
            "issues": unique_issues,
            "suggested_fix": "" if passed else _build_suggested_fix(unique_issues),
            "task_type": task_type,
        }

    allowed_shop_names = {
        name
        for name in (
            item.get("shop_name", "") if isinstance(item, dict) else ""
            for item in (evidence_dict.get("evidence_items") or []) + (evidence_dict.get("unknown_items") or [])
        )
        if isinstance(name, str) and name.strip()
    }
    for name in _known_shop_names_in_answer(answer):
        if allowed_shop_names and name not in allowed_shop_names:
            if f"shop_mismatch:{name}" not in issues:
                issues.append(f"shop_mismatch:{name}")

    facet_results = _extract_facet_results(evidence_dict, task_type)
    for item in facet_results:
        facet = str(item.get("facet", ""))
        if facet and _facet_required(item):
            _facet_rules(answer, facet, item, issues)

    expected_names = _extract_ranked_shop_names(evidence_dict)
    if len(expected_names) >= 2:
        mentioned_order = _extract_mentioned_order(answer, expected_names)
        if len(mentioned_order) >= 2 and mentioned_order != expected_names[: len(mentioned_order)]:
            if "ranking_changed_by_llm" not in issues:
                issues.append("ranking_changed_by_llm")
    if task_type == "recommendation" and len(expected_names) >= 3:
        mentioned_order = _extract_mentioned_order(answer, expected_names)
        if len(mentioned_order) != 3:
            if "recommendation_top_k_mismatch" not in issues:
                issues.append("recommendation_top_k_mismatch")

    # Deduplicate issues
    unique_issues = []
    for issue in issues:
        if issue not in unique_issues:
            unique_issues.append(issue)

    passed = len(unique_issues) == 0
    return {
        "passed": passed,
        "issues": unique_issues,
        "suggested_fix": "" if passed else _build_suggested_fix(unique_issues),
        "task_type": task_type,
    }

