"""Answer verifier for local-life flows."""

from __future__ import annotations

import re
from typing import Any


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


_SHOP_MENTION_PATTERN = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9·]{2,40}(?:\([^)]+\))?(?:店|馆|楼|城|中心店|广场店|餐厅|咖啡店|火锅店|茶餐厅|烧烤店|烤肉店)?"
)

_SHOP_PREFIXES = (
    "为您推荐",
    "给您推荐",
    "推荐顺序是",
    "推荐顺序为",
    "推荐是",
    "对比",
    "比较",
    "优先看",
    "先看",
    "先去",
    "建议去",
    "可以去",
    "也可以去",
    "你也可以去",
    "顺便去",
    "去",
    "到",
    "看",
    "看看",
    "这家是",
    "这家",
    "第一家是",
    "第一家",
    "上述几家",
    "上述几店",
    "上述",
)

_SHOP_SUFFIXES = (
    "看看",
    "试试",
    "吧",
    "呢",
    "哦",
)


def _append_shop_name(names: set[str], value: Any) -> None:
    name = str(value or "").strip()
    if not name:
        return
    names.add(name)
    if "(" in name:
        names.add(name.split("(", 1)[0].strip())


def _strip_shop_context(candidate: str) -> str:
    text = candidate.strip().strip("，。；;：:、, ")
    if not text:
        return text
    changed = True
    while changed and text:
        changed = False
        for prefix in sorted(_SHOP_PREFIXES, key=len, reverse=True):
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix):].lstrip("，。；;：:、, \t")
                changed = True
        for suffix in sorted(_SHOP_SUFFIXES, key=len, reverse=True):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].rstrip("，。；;：:、, \t")
                changed = True
    return text


def _collect_allowed_shop_names(evidence: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("shop_name", "name", "alias"):
                if value.get(key):
                    _append_shop_name(allowed, value.get(key))
            for key in ("ranking_snapshot", "comparison_matrix", "candidate_summaries", "evidence_items", "unknown_items", "last_recommendation_list", "comparison_targets"):
                child = value.get(key)
                if child is not None:
                    walk(child)
            for key in ("ranked", "ranked_shops", "shops", "rows", "overall_ranked", "dimension_winners", "items"):
                child = value.get(key)
                if child is not None:
                    walk(child)
            for item in value.values():
                if isinstance(item, (dict, list, tuple)):
                    walk(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
            return
        if isinstance(value, str):
            return

    walk(evidence)
    return allowed


def _known_shop_names_in_answer(answer: str) -> list[str]:
    """Extract explicit shop-like mentions from the answer text."""
    mentions: list[str] = []
    for match in _SHOP_MENTION_PATTERN.finditer(answer):
        raw_candidate = _strip_shop_context(match.group(0))
        if not raw_candidate:
            continue
        pieces = [raw_candidate]
        if any(sep in raw_candidate for sep in ("和", "与", "及", "、", "，", ",", "；", ";", "/")):
            split_pieces = [part.strip() for part in re.split(r"[和与及、，,；;/]", raw_candidate) if part.strip()]
            if len(split_pieces) >= 2:
                pieces = split_pieces
        for candidate in pieces:
            candidate = _strip_shop_context(candidate)
            if not candidate:
                continue
            if "(" not in candidate and not candidate.endswith(("店", "馆", "楼", "城", "餐厅", "咖啡店", "火锅店", "茶餐厅", "烧烤店", "烤肉店", "中心店", "广场店")):
                continue
            if candidate not in mentions:
                mentions.append(candidate)
    return mentions


def _closest_expected_name(answer: str, expected_names: list[str], phrase_index: int) -> str:
    best_name = ""
    best_distance: int | None = None
    for name in expected_names:
        if not name:
            continue
        index = answer.find(name)
        if index < 0:
            continue
        distance = abs(index - phrase_index)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name


def _extract_facet_results(evidence: dict[str, Any], task_type: str) -> list[dict[str, Any]]:
    facet_results = evidence.get("facet_results") or []
    if facet_results:
        return [item if isinstance(item, dict) else {} for item in facet_results]
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
        tool_name = str(item.get("tool_name", "") or "").strip()
        is_straight_line_tool = tool_name == "calculate_distance_km" or bool(
            isinstance(distance_value, dict) and str(distance_value.get("method", "") or "").lower() == "haversine"
        )
        if status == "ok":
            if distance_km is not None:
                expected = str(distance_km)
                if expected not in answer and not _match_any_regex(answer, [r"\d+(\.\d+)?\s*(\u516c\u91cc|km|\u7c73)"]):
                    issues.append("distance_missing_numeric_claim")
                if is_straight_line_tool and not _match_any_phrase(answer, ["直线距离", "直线"]):
                    issues.append("distance_missing_straight_line_claim")
                if is_straight_line_tool and _match_any_regex(answer, [r"\u9884\u8ba1", r"\d+\s*\u5206\u949f", r"\u6b65\u884c", r"\u9a7e\u8f66", r"\u5f00\u8f66", r"\u8def\u7ebf", r"\u591a\u4e45\u5230"]):
                    issues.append("distance_false_eta_claim")
        elif status in {"unknown", "failed"}:
            if _match_any_regex(answer, [r"\u5f88\u8fd1", r"\u4e0d\u8fdc", r"\u5f88\u8fdc", r"\d+\s*\u5206\u949f", r"\u51e0\u5206\u949f"]):
                issues.append("distance_false_positive")
            if is_straight_line_tool and _match_any_phrase(answer, ["直线距离", "直线"]) and not _match_any_phrase(answer, ["无法确认", "暂时无法确认", "获取距离信息失败", "稍后再试"]):
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
        ranking_snapshot = evidence.get("ranking_snapshot") or {}
        rows = [row for row in (ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or ranking_snapshot.get("shops") or []) if isinstance(row, dict)]
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

    expected_names = _comparison_overall_ranked_names(evidence) or _comparison_shop_names(evidence) or _extract_ranked_shop_names(evidence)
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

    ordering_markers = ["\u5728\u524d", "\u5728\u540e", "\u6392\u5728", "\u987a\u5e8f", "\u6392\u540d", "\u524d\u9762", "\u540e\u9762", "\u7b2c\u4e00", "\u7b2c\u4e8c", "\u7b2c\u4e09"]
    if len(expected_names) >= 2 and _match_any_phrase(answer, ordering_markers):
        mentioned_order = _extract_mentioned_order(answer, expected_names)
        if len(mentioned_order) >= 2 and mentioned_order != expected_names[: len(mentioned_order)]:
            issues.append("ranking_changed_by_llm")

    winner_claim_phrases = ["\u6700\u63a8\u8350", "\u66f4\u597d", "\u66f4\u4f18", "\u80dc\u51fa", "\u9886\u5148", "\u7efc\u5408\u6700\u597d", "\u7efc\u5408\u66f4\u597d", "\u66f4\u9002\u5408", "\u66f4\u8fd1", "\u79bb\u5f97\u66f4\u8fd1", "\u6700\u8fd1"]
    if len(expected_names) >= 2 and _match_any_phrase(answer, winner_claim_phrases):
        winner_claimed = False
        for phrase in winner_claim_phrases:
            start = 0
            while True:
                phrase_index = answer.find(phrase, start)
                if phrase_index < 0:
                    break
                closest_name = _closest_expected_name(answer, expected_names, phrase_index)
                if closest_name and closest_name != expected_names[0]:
                    issues.append("unsupported_comparison_winner")
                    winner_claimed = True
                    break
                start = phrase_index + len(phrase)
            if winner_claimed:
                break

    return issues


def _build_suggested_fix(issues: list[str]) -> str:
    parts: list[str] = []
    if any(issue == "grounded_fact_downgraded_to_unknown" for issue in issues):
        parts.append("已确认的营业、优惠、评分、价格或距离事实不能改写成暂时无法确认，只能对对应的 unknown / failed / partial facet 保持保守。")
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
    from .b2_mini_verifier import B2MiniVerifier
    from .generator import _build_decision_plan

    mock_answer_plan = {
        "answer_type": task_type,
        "forbidden_claims": evidence_dict.get("forbidden_claims") or [],
        "must_mention_unknowns": [
            item.get("shop_name", "") if isinstance(item, dict) else str(item)
            for item in (evidence_dict.get("unknown_items") or [])
            if (item.get("shop_name", "") if isinstance(item, dict) else str(item))
        ],
    }
    plan = _build_decision_plan(mock_answer_plan, evidence_dict)
    res = B2MiniVerifier().verify(plan, answer)
    issues = list(res.get("violations") or [])
    passed = bool(res.get("passed", False))
    if not passed and not issues:
        fallback_code = str(res.get("failure_code") or res.get("violation") or "verifier_failed")
        issues = [fallback_code]
    return {
        "passed": passed,
        "issues": issues,
        "suggested_fix": "" if passed else _build_suggested_fix(issues),
        "task_type": task_type,
    }

