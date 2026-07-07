"""Answer verifier for local-life flows."""

from __future__ import annotations

import re
from typing import Any

from .b2_mini_verifier import _heuristic_verify


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


def _contains_uncertainty_notice(text: str) -> bool:
    return _match_any_phrase(
        text,
        [
            "暂时无法确认",
            "无法确认",
            "暂时没查到",
            "没查到",
            "还不确定",
            "不确定",
            "稍后再试",
            "目前只能确认",
            "部分信息",
            "部分阶段",
            "还需要补充",
        ],
    )


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
        for prefix in ("暂时", "目前", "当前", "大概", "大约", "约", "先", "这家", "那家"):
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix):].lstrip("，。；;：:、, \t")
                changed = True
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
    evidence_items = evidence.get("evidence_items") or []
    result: list[dict[str, Any]] = []
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        facet = str(normalized.get("facet") or "").strip()
        if not facet:
            continue
        if not normalized.get("status") and not normalized.get("result_status"):
            value = normalized.get("value")
            if facet == "open_status" and str(value or "").strip().lower() in {"open", "closed"}:
                normalized["status"] = "ok"
            elif facet == "coupon":
                if isinstance(value, list):
                    normalized["status"] = "ok" if value else "empty"
                elif value is not None:
                    normalized["status"] = "ok"
            elif facet in {"distance", "rating", "avg_price", "detail"} and value is not None:
                normalized["status"] = "ok"
        result.append(normalized)
    return result


def _needs_llm_verification(plan: dict[str, Any], evidence: dict[str, Any]) -> bool:
    answer_type = str(plan.get("answer_type", "") or "").strip()
    if answer_type in {"comparison", "exploration_plan", "exploration"}:
        return True
    if answer_type == "recommendation":
        comparison_matrix = evidence.get("comparison_matrix") or {}
        if isinstance(comparison_matrix, dict) and (comparison_matrix.get("rows") or comparison_matrix.get("overall_ranked")):
            return True
    selected_targets = plan.get("selected_targets") or []
    if isinstance(selected_targets, list) and len([item for item in selected_targets if isinstance(item, dict)]) > 2:
        return True
    if evidence.get("answer_verify_force_llm"):
        return True
    return False


def _facet_status_text(facet: str, item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("result_status") or "unknown")


def _facet_required(item: dict[str, Any]) -> bool:
    return bool(item.get("required", True))


def _facet_rules(answer: str, facet: str, item: dict[str, Any], issues: list[str], task_type: str) -> None:
    status = _facet_status_text(facet, item)
    if facet == "coupon":
        coupon_related = _match_any_phrase(answer, ["\u4f18\u60e0\u5238", "\u4f18\u60e0\u60c5\u51b5", "\u6709\u5238", "\u53ef\u7528\u5238", "\u4f18\u60e0"])
        if task_type in {"recommendation", "comparison"} and not coupon_related:
            return
        if status == "ok":
            if not _match_any_phrase(answer, ["\u6709\u5238", "\u53ef\u7528\u5238", "\u4f18\u60e0\u5238"]):
                issues.append("coupon_status_missing_positive_claim")
        elif status == "empty":
            if _match_any_regex(answer, [r"(?<!\u6ca1)\u6709\u5238", r"\u6709\u53ef\u7528\u5238", r"\u6709\u4f18\u60e0\u5238"]):
                issues.append("coupon_status_false_positive")
            if not _match_any_phrase(answer, ["\u6682\u65e0\u53ef\u7528\u5238", "\u6ca1\u6709\u5238", "\u5f53\u524d\u6682\u65e0\u53ef\u7528\u5238"]):
                issues.append("coupon_status_missing_empty_notice")
        elif status == "unknown":
            if _match_any_regex(answer, [r"(?<!\u6ca1)\u6709\u5238", r"\u6709\u53ef\u7528\u5238", r"\u6709\u4f18\u60e0\u5238", r"\u6682\u65e0\u53ef\u7528\u5238", r"\u6ca1\u6709\u4f18\u60e0\u5238", r"\u6ca1\u6709\u5238", r"\u65e0\u4f18\u60e0\u5238", r"\u6ca1\u6709\u4f18\u60e0\u5238"]):
                issues.append("unknown_claimed_as_empty_or_available")
                issues.append("unsupported_coupon")
            if coupon_related and not _match_any_phrase(answer, ["\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u4f18\u60e0\u5238\u60c5\u51b5", "\u83b7\u53d6\u4f18\u60e0\u5238\u4fe1\u606f\u5931\u8d25", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("unknown_needs_uncertain_notice")
        elif status == "failed":
            if coupon_related and not _match_any_phrase(answer, ["\u83b7\u53d6\u4f18\u60e0\u5238\u4fe1\u606f\u5931\u8d25", "\u5efa\u8bae\u7a0d\u540e\u518d\u8bd5", "\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u4f18\u60e0\u5238\u60c5\u51b5"]):
                issues.append("failed_needs_failure_notice")
        elif status == "circuit_open":
            if coupon_related and not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("circuit_open_needs_unavailable_notice")
        return

    if facet == "open_status":
        open_status = str(item.get("open_status") or item.get("value") or "").lower()
        open_related = _match_any_phrase(answer, ["\u8425\u4e1a", "\u5f00\u95e8", "\u5173\u95e8", "\u6253\u70ca", "\u4e0d\u8425\u4e1a", "\u8425\u4e1a\u72b6\u6001"])
        if task_type in {"recommendation", "comparison"} and not open_related:
            return
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
            if _match_any_phrase(answer, ["\u8425\u4e1a\u4e2d", "\u6b63\u5728\u8425\u4e1a", "\u6b63\u5e38\u8425\u4e1a", "\u5df2\u6253\u70ca", "\u5df2\u5173\u95e8", "\u4e0d\u8425\u4e1a", "\u73b0\u5728\u4e0d\u8425\u4e1a\u4e86"]):
                issues.append("open_status_false_positive")
                issues.append("unsupported_open_status")
            if open_related and not _match_any_phrase(answer, ["\u65e0\u6cd5\u786e\u8ba4\u8425\u4e1a\u72b6\u6001", "\u8425\u4e1a\u72b6\u6001\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4", "\u83b7\u53d6\u8425\u4e1a\u72b6\u6001\u5931\u8d25", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("open_status_needs_uncertain_notice")
        elif status == "circuit_open":
            if open_related and not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
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
        distance_related = _match_any_phrase(answer, ["\u8ddd\u79bb", "\u516c\u91cc", "km", "\u7c73", "\u4e0d\u8fdc", "\u5f88\u8fd1", "\u5f88\u8fdc", "\u51e0\u5206\u949f", "\u5206\u949f", "\u8def\u7a0b"])
        if task_type in {"recommendation", "comparison"} and not distance_related:
            return
        if status == "ok":
            if distance_km is not None:
                expected = str(distance_km)
                number_matches = re.findall(r"\d+(?:\.\d+)?", answer)
                if expected not in answer:
                    if number_matches:
                        issues.append("unsupported_distance")
                    else:
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
        elif status == "circuit_open":
            if distance_related and not _match_any_phrase(answer, ["\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528", "\u7a0d\u540e\u518d\u8bd5"]):
                issues.append("distance_needs_unavailable_notice")


    if facet == "rating":
        rating_value = item.get("rating", item.get("value"))
        rating_related = _match_any_phrase(answer, ["\u8bc4\u5206", "\u53e3\u7891"])
        shop_name = str(item.get("shop_name") or item.get("name") or item.get("shop_id") or "").strip()
        if task_type in {"recommendation", "comparison"} and shop_name:
            short_name = shop_name.split("(", 1)[0].strip()
            if shop_name not in answer and short_name not in answer:
                return
        if rating_value is not None and rating_related:
            expected = str(rating_value).strip()
            if not _match_any_regex(answer, [rf"{re.escape(expected)}(?:\u5206|\u661f)?"]):
                issues.append("unsupported_rating")
        return

    if facet == "avg_price":
        price_value = item.get("avg_price", item.get("value"))
        price_related = _match_any_phrase(answer, ["\u4eba\u5747", "\u4ef7\u683c", "\u6d88\u8d39"])
        if task_type in {"recommendation", "comparison"} and not price_related:
            return
        if price_value is not None and price_related:
            expected = str(price_value).strip()
            if not _match_any_regex(answer, [rf"{re.escape(expected)}(?:\u5143|\u5757|\u4eba\u6c11\u5e01)?"]):
                issues.append("unsupported_price")
        return


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


def _comparison_statistical_winner(evidence: dict[str, Any]) -> dict[str, Any]:
    matrix = evidence.get("comparison_matrix") or {}
    winner = matrix.get("statistical_winner") or {}
    return winner if isinstance(winner, dict) else {}


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
        statistical_winner = _comparison_statistical_winner(evidence)
        winner_name = str(statistical_winner.get("shop_name", "") or statistical_winner.get("shop_id", "") or "").strip()
        winner_claimed = False
        for phrase in winner_claim_phrases:
            start = 0
            while True:
                phrase_index = answer.find(phrase, start)
                if phrase_index < 0:
                    break
                if not winner_name:
                    issues.append("unsupported_comparison_winner")
                    winner_claimed = True
                    break
                closest_name = _closest_expected_name(answer, expected_names, phrase_index)
                if not closest_name:
                    issues.append("unsupported_comparison_winner")
                    winner_claimed = True
                    break
                if closest_name != winner_name:
                    issues.append("unsupported_comparison_winner")
                    winner_claimed = True
                    break
                start = phrase_index + len(phrase)
            if winner_claimed:
                break

    return issues


def _extract_expected_claims(plan: dict[str, Any], evidence: dict[str, Any], task_type: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_claim(payload: dict[str, Any]) -> None:
        claim_id = str(payload.get("claim_id", "") or "").strip()
        if not claim_id:
            return
        if claim_id in seen_ids:
            return
        seen_ids.add(claim_id)
        claims.append(payload)

    plan_dict = _to_dict(plan)
    evidence_dict = _to_dict(evidence)

    for source_name in ("allowed_claims", "required_claims"):
        for index, item in enumerate(plan_dict.get(source_name) or [], start=1):
            item_dict = _to_dict(item)
            claim_id = str(item_dict.get("claim_id", "") or f"{source_name}_{index}").strip()
            facet = str(item_dict.get("facet", item_dict.get("claim_type", "")) or "").strip()
            claim_type = str(item_dict.get("claim_type", facet or "factual")).strip() or "factual"
            shop_id = str(item_dict.get("shop_id", "") or "").strip()
            shop_name = str(item_dict.get("shop_name", "") or item_dict.get("verbalization_hint", "") or "").strip()
            value = item_dict.get("value")
            evidence_refs = [str(ref).strip() for ref in (item_dict.get("evidence_ids") or item_dict.get("evidence_refs") or []) if str(ref).strip()]
            add_claim(
                {
                    "claim_id": claim_id,
                    "claim_type": claim_type,
                    "facet": facet or claim_type,
                    "shop_id": shop_id,
                    "shop_name": shop_name,
                    "value": value,
                    "evidence_refs": evidence_refs,
                    "must_mention": bool(item_dict.get("must_mention", True)),
                    "confidence": float(item_dict.get("confidence", 0.8) or 0.0),
                    "source": source_name,
                }
            )

    ranking_snapshot = evidence_dict.get("ranking_snapshot") or {}
    ranked = ranking_snapshot.get("ranked") or ranking_snapshot.get("ranked_shops") or ranking_snapshot.get("shops") or []
    for index, item in enumerate(ranked, start=1):
        item_dict = _to_dict(item)
        shop_id = str(item_dict.get("shop_id", "") or item_dict.get("id", "") or "").strip()
        shop_name = str(item_dict.get("shop_name", "") or item_dict.get("name", "") or "").strip()
        if not shop_id and not shop_name:
            continue
        add_claim(
            {
                "claim_id": f"recommendation_rank_{index}",
                "claim_type": "recommendation_rank",
                "facet": "recommendation_rank",
                "shop_id": shop_id,
                "shop_name": shop_name,
                "value": {"rank": index, "score": item_dict.get("total_score")},
                "evidence_refs": [str(item_dict.get("evidence_id", "") or "").strip()] if str(item_dict.get("evidence_id", "") or "").strip() else [],
                "must_mention": index == 1,
                "confidence": 1.0,
                "source": "ranking_snapshot",
            }
        )

    comparison_matrix = evidence_dict.get("comparison_matrix") or {}
    statistical_winner = _comparison_statistical_winner(evidence_dict)
    overall_ranked = comparison_matrix.get("overall_ranked") or []
    for index, item in enumerate(overall_ranked, start=1):
        item_dict = _to_dict(item)
        shop_id = str(item_dict.get("shop_id", "") or "").strip()
        shop_name = str(item_dict.get("shop_name", "") or "").strip()
        if not shop_id and not shop_name:
            continue
        add_claim(
            {
                "claim_id": f"comparison_rank_{index}",
                "claim_type": "recommendation_rank",
                "facet": "recommendation_rank",
                "shop_id": shop_id,
                "shop_name": shop_name,
                "value": {"rank": index, "score": item_dict.get("total_score")},
                "evidence_refs": [str(item_dict.get("evidence_id", "") or "").strip()] if str(item_dict.get("evidence_id", "") or "").strip() else [],
                "must_mention": index == 1,
                "confidence": 1.0,
                "source": "comparison_matrix",
            }
        )

    if task_type in {"recommendation", "comparison"} and statistical_winner:
        top_item = _to_dict(statistical_winner)
        top_shop_id = str(top_item.get("shop_id", "") or "").strip()
        top_shop_name = str(top_item.get("shop_name", "") or "").strip()
        if top_shop_id or top_shop_name:
            add_claim(
                {
                    "claim_id": "comparison_winner_overall",
                    "claim_type": "comparison_winner",
                    "facet": "overall_winner",
                    "shop_id": top_shop_id,
                    "shop_name": top_shop_name,
                    "value": top_item.get("reason") or top_item.get("score_breakdown") or "statistical_winner",
                    "evidence_refs": [str(top_item.get("evidence_id", "") or "").strip()] if str(top_item.get("evidence_id", "") or "").strip() else [],
                    "must_mention": True,
                    "confidence": 1.0,
                    "source": "statistical_winner",
                }
            )

    best_for = _to_dict(plan_dict.get("best_for") or {})
    for label, best_item in best_for.items():
        best_dict = _to_dict(best_item)
        shop_id = str(best_dict.get("shop_id", "") or "").strip()
        shop_name = str(best_dict.get("shop_name", "") or "").strip()
        if not shop_id and not shop_name:
            continue
        add_claim(
            {
                "claim_id": f"comparison_winner_{label}",
                "claim_type": "comparison_winner",
                "facet": str(label or "comparison_winner"),
                "shop_id": shop_id,
                "shop_name": shop_name,
                "value": best_dict.get("reason") or label,
                "evidence_refs": [str(best_dict.get("evidence_id", "") or "").strip()] if str(best_dict.get("evidence_id", "") or "").strip() else [],
                "must_mention": True,
                "confidence": float(best_dict.get("confidence", 1.0) or 1.0),
                "source": "best_for",
            }
        )

    for index, point in enumerate(plan_dict.get("factual_points") or [], start=1):
        text = str(point or "").strip()
        if not text:
            continue
        add_claim(
            {
                "claim_id": f"factual_point_{index}",
                "claim_type": "factual_point",
                "facet": "factual_point",
                "shop_id": "",
                "shop_name": "",
                "value": text,
                "evidence_refs": [],
                "must_mention": True,
                "confidence": 0.8,
                "source": "factual_points",
            }
        )

    unknown_notices = list(plan_dict.get("must_mention_unknowns") or []) + list(plan_dict.get("unknown_facets") or []) + list(plan_dict.get("unknown_fields") or [])
    for index, item in enumerate(dict.fromkeys([str(item).strip() for item in unknown_notices if str(item).strip()]), start=1):
        add_claim(
            {
                "claim_id": f"unknown_notice_{index}",
                "claim_type": "unknown_notice",
                "facet": item,
                "shop_id": "",
                "shop_name": "",
                "value": item,
                "evidence_refs": [],
                "must_mention": True,
                "confidence": 0.9,
                "source": "unknown_notice",
            }
        )

    for index, note in enumerate(plan_dict.get("uncertainty_notes") or [], start=1):
        text = str(note or "").strip()
        if not text:
            continue
        add_claim(
            {
                "claim_id": f"tradeoff_{index}",
                "claim_type": "comparison_tradeoff",
                "facet": "comparison_tradeoff",
                "shop_id": "",
                "shop_name": "",
                "value": text,
                "evidence_refs": [],
                "must_mention": True,
                "confidence": 0.8,
                "source": "uncertainty_notes",
            }
        )

    # Preserve task-specific structural signals for downstream rewrite instructions.
    if task_type == "comparison" and comparison_matrix.get("dimension_winners"):
        for dim, winners in (comparison_matrix.get("dimension_winners") or {}).items():
            for index, winner in enumerate(winners or [], start=1):
                winner_dict = _to_dict(winner)
                shop_id = str(winner_dict.get("shop_id", "") or "").strip()
                shop_name = str(winner_dict.get("shop_name", "") or "").strip()
                if not shop_id and not shop_name:
                    continue
                add_claim(
                    {
                        "claim_id": f"dimension_winner_{dim}_{index}",
                        "claim_type": "comparison_winner",
                        "facet": str(dim or "comparison_winner"),
                        "shop_id": shop_id,
                        "shop_name": shop_name,
                        "value": winner_dict.get("reason") or dim,
                        "evidence_refs": [str(winner_dict.get("evidence_id", "") or "").strip()] if str(winner_dict.get("evidence_id", "") or "").strip() else [],
                        "must_mention": True,
                        "confidence": float(winner_dict.get("confidence", 1.0) or 1.0),
                        "source": "dimension_winners",
                    }
                )

    return claims


def _claim_l1_status_from_issues(claim: dict[str, Any], issues: list[str]) -> tuple[str, list[str]]:
    claim_type = str(claim.get("claim_type", "") or "").strip()
    facet = str(claim.get("facet", "") or "").strip()
    claim_id = str(claim.get("claim_id", "") or "").strip()
    issue_set = {str(item).strip() for item in issues if str(item).strip()}

    def has(*candidates: str) -> bool:
        return any(candidate in issue_set for candidate in candidates)

    if claim_type == "recommendation_rank":
        if has("ranking_changed_by_llm", "missing_recommendation_targets", "all_targets_claim_violation"):
            return "unsupported", ["ranking_changed_by_llm"]
        return "supported", []

    if claim_type == "comparison_winner":
        matched = [issue for issue in issue_set if issue in {"unsupported_comparison_winner", "unprovided_dimension_winner", "comparison_matrix_mismatch", "ranking_changed_by_llm"}]
        if matched:
            return "unsupported", matched
        return "supported", []

    if claim_type == "unknown_notice":
        if has("unknown_as_false", "grounded_fact_downgraded_to_unknown", "unknown_needs_uncertain_notice", "tool_failure_as_fact"):
            return "unknown", [issue for issue in issue_set if issue in {"unknown_as_false", "grounded_fact_downgraded_to_unknown", "unknown_needs_uncertain_notice", "tool_failure_as_fact"}]
        return "supported", []

    if facet == "coupon":
        matched = [issue for issue in issue_set if issue.startswith("coupon") or issue.startswith("unknown_") or issue.startswith("tool_failure") or issue.startswith("unsupported_coupon")]
        if matched:
            if any(issue in issue_set for issue in {"unknown_as_false", "tool_failure_as_fact", "unsupported_coupon"}):
                return "contradicted", matched
            return "unsupported", matched
        return "supported", []

    if facet == "open_status":
        matched = [issue for issue in issue_set if issue.startswith("open_status") or issue.startswith("unknown_") or issue.startswith("tool_failure") or issue.startswith("unsupported_open_status")]
        if matched:
            if any(issue in issue_set for issue in {"unknown_as_false", "tool_failure_as_fact", "unsupported_open_status"}):
                return "contradicted", matched
            return "unsupported", matched
        return "supported", []

    if facet == "distance":
        matched = [issue for issue in issue_set if issue.startswith("distance") or issue.startswith("unknown_") or issue.startswith("tool_failure") or issue.startswith("unsupported_distance")]
        if matched:
            if any(issue in issue_set for issue in {"distance_false_positive", "distance_false_eta_claim", "unknown_as_false", "tool_failure_as_fact", "unsupported_distance"}):
                return "contradicted", matched
            return "unsupported", matched
        return "supported", []

    if facet == "rating":
        matched = [issue for issue in issue_set if issue.startswith("unsupported_rating")]
        if matched:
            return "unsupported", matched
        return "supported", []

    if facet == "avg_price":
        matched = [issue for issue in issue_set if issue.startswith("unsupported_price")]
        if matched:
            return "unsupported", matched
        return "supported", []

    if claim_type == "factual_point":
        if has("grounded_fact_downgraded_to_unknown", "tool_failure_as_fact"):
            return "unknown", [issue for issue in issue_set if issue in {"grounded_fact_downgraded_to_unknown", "tool_failure_as_fact"}]
        return "supported", []

    return ("unknown", [issue for issue in issue_set if issue.startswith("unknown_")]) if has("unknown_as_false") else ("supported", [])


def _claim_span_candidates(claim: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("text", "claim_text", "shop_name", "value", "facet"):
        value = str(claim.get(key, "") or "").strip()
        if value:
            candidates.append(value)
            if "(" in value:
                candidates.append(value.split("(", 1)[0].strip())
            if "（" in value:
                candidates.append(value.split("（", 1)[0].strip())
    return [item for item in dict.fromkeys(candidates) if item]


def _with_claim_span(claim: dict[str, Any], answer: str) -> dict[str, Any]:
    result = dict(claim)
    answer_text = str(answer or "")
    for candidate in _claim_span_candidates(claim):
        start = answer_text.find(candidate)
        if start >= 0:
            result.update(
                {
                    "span_text": candidate,
                    "span_start": start,
                    "span_end": start + len(candidate),
                    "span_confidence": "high",
                    "claim_span_level": "l2_text_span",
                }
            )
            return result
    result.update(
        {
            "span_text": "",
            "span_start": -1,
            "span_end": -1,
            "span_confidence": "low",
            "claim_span_level": "l2_text_span",
        }
    )
    return result


def _structured_claim_supported(claim: dict[str, Any], expected_claims: list[dict[str, Any]]) -> bool:
    claim_type = str(claim.get("claim_type", "") or "").strip()
    shop_id = str(claim.get("shop_id", "") or "").strip()
    shop_name = str(claim.get("shop_name", "") or "").strip()
    if not claim_type:
        return False
    compatible_types = {
        "comparison_winner": {"comparison_winner"},
        "winner": {"comparison_winner"},
        "recommendation_rank": {"recommendation_rank"},
        "ranking": {"recommendation_rank"},
        "coupon": {"single_shop_fact"},
        "open_status": {"single_shop_fact"},
        "distance": {"single_shop_fact"},
        "rating": {"single_shop_fact"},
    }
    expected_types = compatible_types.get(claim_type, {claim_type})
    for expected in expected_claims:
        expected_type = str(expected.get("claim_type", "") or "").strip()
        if expected_type not in expected_types:
            continue
        expected_id = str(expected.get("shop_id", "") or "").strip()
        expected_name = str(expected.get("shop_name", "") or "").strip()
        if shop_id and expected_id and shop_id != expected_id:
            continue
        if shop_name and expected_name and shop_name != expected_name:
            continue
        return True
    return False


def _apply_structured_l3_claims(report: dict[str, Any], answer: str, extracted_claims: list[dict[str, Any]]) -> dict[str, Any]:
    if not extracted_claims:
        return report
    expected_claims = [item for item in (report.get("expected_claims") or []) if isinstance(item, dict)]
    claim_results = list(report.get("claim_results") or [])
    unsupported_claims = list(report.get("unsupported_claims") or [])
    issues = list(report.get("issues") or [])
    supported_claims = list(report.get("supported_claims") or [])
    for index, raw_claim in enumerate(extracted_claims, start=1):
        claim = dict(raw_claim)
        text = str(claim.get("text") or claim.get("claim_text") or "").strip()
        claim_id = str(claim.get("claim_id") or f"l3_structured_claim_{index}")
        supported = _structured_claim_supported(claim, expected_claims)
        result = _with_claim_span(
            {
                **claim,
                "claim_id": claim_id,
                "status": "supported" if supported else "unsupported",
                "matched_issues": [] if supported else ["unsupported_structured_claim"],
                "claim_extractor_level": "l3_structured_llm",
            },
            answer,
        )
        claim_results.append(result)
        if supported:
            supported_claims.append(claim_id)
            continue
        if "unsupported_structured_claim" not in issues:
            issues.append("unsupported_structured_claim")
        unsupported_claims.append(text or claim_id)
    patched = dict(report)
    patched["claim_results"] = claim_results
    patched["supported_claims"] = list(dict.fromkeys([item for item in supported_claims if item]))
    patched["unsupported_claims"] = list(dict.fromkeys([item for item in unsupported_claims if item]))
    patched["issues"] = list(dict.fromkeys([item for item in issues if item]))
    patched["claim_extractor"] = "l3_structured_llm"
    patched["verification_mode"] = "claim_l3"
    if "unsupported_structured_claim" in patched["issues"]:
        patched["passed"] = False
        patched["recoverable"] = True
        patched["failure_code"] = patched.get("failure_code") or "unsupported_structured_claim"
        patched["suggested_fix"] = _build_suggested_fix(patched["issues"])
    return patched


def _claim_l1_report(plan: dict[str, Any], evidence: dict[str, Any], answer: str, task_type: str) -> dict[str, Any]:
    base_report = _deterministic_verify(answer, evidence, task_type)
    issues = list(base_report.get("issues") or [])
    expected_claims = _extract_expected_claims(plan, evidence, task_type)
    claim_results: list[dict[str, Any]] = []
    supported_claims: list[str] = []
    unsupported_claims: list[str] = []
    contradicted_claims: list[str] = []
    unknown_claims: list[str] = []
    unknown_fields: list[str] = []

    for claim in expected_claims:
        status, matched_issues = _claim_l1_status_from_issues(claim, issues)
        claim_id = str(claim.get("claim_id", "") or "").strip()
        result = {
            **claim,
            "status": status,
            "matched_issues": matched_issues,
        }
        claim_results.append(_with_claim_span(result, answer))
        if status == "supported":
            supported_claims.append(claim_id)
        elif status == "unsupported":
            unsupported_claims.append(claim_id)
        elif status == "contradicted":
            contradicted_claims.append(claim_id)
        else:
            unknown_claims.append(claim_id)
            facet = str(claim.get("facet", "") or "").strip()
            if facet:
                unknown_fields.append(facet)

    unsupported_claim_texts = [claim_id for claim_id in unsupported_claims if claim_id]
    contradicted_claim_texts = [claim_id for claim_id in contradicted_claims if claim_id]
    unknown_field_texts = [item for item in dict.fromkeys([item for item in unknown_fields if item])]
    if any(claim.get("claim_type") == "unknown_notice" for claim in expected_claims) and _contains_uncertainty_notice(answer):
        supported_claims.extend([claim["claim_id"] for claim in expected_claims if claim.get("claim_type") == "unknown_notice" and claim.get("claim_id") not in supported_claims])

    return {
        **base_report,
        "claim_results": claim_results,
        "supported_claims": list(dict.fromkeys([item for item in supported_claims if item])),
        "unsupported_claims": list(dict.fromkeys([item for item in unsupported_claim_texts if item])),
        "contradicted_claims": list(dict.fromkeys([item for item in contradicted_claim_texts if item])),
        "unknown_fields": list(dict.fromkeys([item for item in unknown_field_texts if item])),
        "false_fields": list(dict.fromkeys([item for item in contradicted_claim_texts if item])),
        "expected_claims": expected_claims,
        "claim_extractor": "l1_structured",
        "verification_mode": "claim_l1",
    }


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


def _deterministic_verify(answer: str, evidence: dict[str, Any], task_type: str) -> dict[str, Any]:
    evidence_dict = _to_dict(evidence)
    issues: list[str] = []

    facet_results = _extract_facet_results(evidence_dict, task_type)
    if not facet_results:
        selected_targets = [item for item in (evidence_dict.get("selected_targets") or []) if isinstance(item, dict)]
        if selected_targets:
            target = dict(selected_targets[0])
            facet_statuses = dict(evidence_dict.get("facet_statuses") or {})
            synthetic_items: list[dict[str, Any]] = []
            open_status = str(target.get("open_status") or facet_statuses.get("open_status") or "").strip().lower()
            if open_status:
                synthetic_items.append(
                    {
                        "facet": "open_status",
                        "status": "ok" if open_status in {"open", "closed"} or facet_statuses.get("open_status") == "grounded" else open_status,
                        "value": open_status,
                        "open_status": open_status,
                    }
                )
            coupon_status = str(target.get("coupon_status") or facet_statuses.get("coupon") or "").strip().lower()
            if coupon_status or target.get("coupon_titles") is not None:
                synthetic_items.append(
                    {
                        "facet": "coupon",
                        "status": "ok" if coupon_status in {"has_coupon", "grounded"} or facet_statuses.get("coupon") == "grounded" else coupon_status or "unknown",
                        "value": target.get("coupon_titles") or coupon_status,
                    }
                )
            distance_value = target.get("distance_km")
            if distance_value is not None or facet_statuses.get("distance"):
                synthetic_items.append(
                    {
                        "facet": "distance",
                        "status": "ok" if distance_value is not None else str(facet_statuses.get("distance") or "unknown"),
                        "value": distance_value,
                        "distance_km": distance_value,
                    }
                )
            rating_value = target.get("rating")
            if rating_value is not None:
                synthetic_items.append({"facet": "rating", "status": "ok", "value": rating_value, "rating": rating_value})
            avg_price_value = target.get("avg_price")
            if avg_price_value is not None:
                synthetic_items.append({"facet": "avg_price", "status": "ok", "value": avg_price_value, "avg_price": avg_price_value})
            facet_results = synthetic_items
    for item in facet_results:
        if not isinstance(item, dict):
            continue
        facet = str(item.get("facet") or "").strip()
        if facet:
            _facet_rules(answer, facet, item, issues, task_type)

    for claim in [str(item).strip() for item in (evidence_dict.get("forbidden_claims") or []) if str(item).strip()]:
        if claim and claim in answer:
            issues.append(f"forbidden_claim:{claim}")

    if task_type == "comparison":
        issues.extend(_comparison_issues(answer, evidence_dict))

    allowed_names = _collect_allowed_shop_names(evidence_dict)
    mentioned_names = _known_shop_names_in_answer(answer)
    if mentioned_names:
        for name in mentioned_names:
            if allowed_names and name not in allowed_names:
                issues.append("hallucinated_shop_name")
                break

    unknown_items = [item for item in (evidence_dict.get("unknown_items") or []) if isinstance(item, dict)]
    unknown_names = [str(item.get("shop_name") or "").strip() for item in unknown_items if str(item.get("shop_name") or "").strip()]
    if unknown_names and _match_any_phrase(answer, ["所有店", "全部", "都"]):
        if not any(name and name in answer for name in unknown_names):
            issues.append("omitted_targets_violation")
            if task_type in {"recommendation", "comparison"}:
                issues.append("all_targets_claim_violation")

    selected_targets = [item for item in (evidence_dict.get("selected_targets") or []) if isinstance(item, dict)]
    if selected_targets:
        if _contains_uncertainty_notice(answer) and any(
            issue in {
                "coupon_status_missing_positive_claim",
                "open_status_missing_open_claim",
                "open_status_missing_closed_claim",
                "distance_missing_numeric_claim",
                "unsupported_rating",
                "unsupported_price",
            }
            for issue in issues
        ):
            issues.append("grounded_fact_downgraded_to_unknown")
        if _match_any_phrase(answer, ["所有店", "全部", "都"]) and task_type in {"recommendation", "comparison"}:
            issues.append("all_targets_claim_violation")

    if "hallucinated_shop_name" in issues and "shop_mismatch" not in issues:
        issues.append("shop_mismatch")
    if any(issue in {"unknown_claimed_as_empty_or_available", "open_status_false_positive", "distance_false_positive"} for issue in issues) and "unknown_as_false" not in issues:
        issues.append("unknown_as_false")
    if any(issue in {"failed_needs_failure_notice", "circuit_open_needs_unavailable_notice", "open_status_needs_unavailable_notice", "distance_needs_unavailable_notice"} for issue in issues) and "tool_failure_as_fact" not in issues:
        issues.append("tool_failure_as_fact")
    if any(issue.startswith("open_status_missing") for issue in issues) and "open_status" not in issues:
        issues.append("open_status")
    if any(issue.startswith("coupon_status_missing") for issue in issues) and "coupon" not in issues:
        issues.append("coupon")

    normalized_issues: list[str] = []
    for issue in issues:
        if issue and issue not in normalized_issues:
            normalized_issues.append(issue)

    if not normalized_issues:
        return {
            "passed": True,
            "issues": [],
            "suggested_fix": "",
            "task_type": task_type,
            "verification_mode": "deterministic",
        }
    return {
        "passed": False,
        "issues": normalized_issues,
        "suggested_fix": _build_suggested_fix(normalized_issues),
        "task_type": task_type,
        "verification_mode": "deterministic",
    }


def verify_answer(
    answer: str,
    evidence: dict,
    task_type: str,
    *,
    answer_source: str = "",
    extracted_claims: list[dict[str, Any]] | None = None,
) -> dict:
    """Verify an answer against its evidence base."""
    evidence_dict = _to_dict(evidence)
    answer_text = str(answer or "").strip()
    structured_claims = [dict(item) for item in (extracted_claims or []) if isinstance(item, dict)]
    if not evidence_dict or not answer_text:
        return {
            "passed": False,
            "issues": ["empty_evidence_or_draft"],
            "suggested_fix": "请先提供有效证据与草稿，再生成回答。",
            "task_type": task_type,
            "verification_mode": "empty_input",
            "failure_code": "empty_evidence_or_draft",
            "recoverable": True,
        }

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
    heuristic = _heuristic_verify(plan, answer_text)
    claim_report = _claim_l1_report(plan, evidence_dict, answer_text, task_type)
    needs_llm = _needs_llm_verification(mock_answer_plan, evidence_dict)
    if not needs_llm:
        result = _deterministic_verify(answer_text, evidence_dict, task_type)
        result.setdefault("failure_code", result.get("issues", [""])[0] if result.get("issues") else "")
        result.setdefault("recoverable", not bool(result.get("passed", False)))
        result.update(
            {
                "claim_results": claim_report.get("claim_results", []),
                "supported_claims": claim_report.get("supported_claims", []),
                "unsupported_claims": claim_report.get("unsupported_claims", []),
                "contradicted_claims": claim_report.get("contradicted_claims", []),
                "expected_claims": claim_report.get("expected_claims", []),
                "claim_extractor": claim_report.get("claim_extractor", ""),
                "verification_mode": result.get("verification_mode", "deterministic"),
            }
        )
        return _apply_structured_l3_claims(result, answer_text, structured_claims)

    res = B2MiniVerifier().verify(plan, answer_text)
    issues = list(res.get("violations") or [])
    passed = bool(res.get("passed", False))
    verification_mode = "llm"
    if not passed and not issues:
        fallback_code = str(res.get("failure_code") or res.get("violation") or "verifier_failed")
        issues = [fallback_code]
    if not passed and heuristic.get("passed", False):
        issues = list(issues or heuristic.get("violations") or [])
        if not issues:
            fallback_code = str(heuristic.get("failure_code") or heuristic.get("violation") or "verifier_failed")
            issues = [fallback_code]
    combined_issues = list(dict.fromkeys([*issues, *(claim_report.get("issues") or [])]))
    passed = bool(passed and not (claim_report.get("unsupported_claims") or claim_report.get("contradicted_claims")))
    result = {
        "passed": passed,
        "issues": combined_issues,
        "suggested_fix": "" if passed else _build_suggested_fix(combined_issues),
        "task_type": task_type,
        "verification_mode": "llm_with_claim_l1",
        "failure_code": str(res.get("failure_code") or res.get("violation") or (issues[0] if issues else "")),
        "recoverable": bool(res.get("recoverable", not passed)),
        "claim_results": claim_report.get("claim_results", []),
        "supported_claims": claim_report.get("supported_claims", []),
        "unsupported_claims": claim_report.get("unsupported_claims", []),
        "contradicted_claims": claim_report.get("contradicted_claims", []),
        "expected_claims": claim_report.get("expected_claims", []),
        "claim_extractor": claim_report.get("claim_extractor", ""),
        "unknown_fields": list(dict.fromkeys([*(res.get("unknown_fields") or []), *(claim_report.get("unknown_fields") or [])])),
        "false_fields": list(dict.fromkeys([*(res.get("false_fields") or []), *(claim_report.get("false_fields") or [])])),
    }
    return _apply_structured_l3_claims(result, answer_text, structured_claims)

