from __future__ import annotations

from typing import Any


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase and phrase in text for phrase in phrases)


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


def fake_verifier_verify(self, plan: Any, response_text: str, **_: Any) -> dict[str, Any]:
    """Test-only verifier stub.

    The production verifier is pure LLM.  The unit tests in this repo
    still need deterministic outputs so they can assert the surrounding
    orchestration contract without depending on a live model.
    """

    plan_dict = _to_dict(plan)
    answer_type = str(plan_dict.get("answer_type", "") or "")
    selected_targets = [item for item in (plan_dict.get("selected_targets") or []) if isinstance(item, dict)]
    overall_ranking = [item for item in (plan_dict.get("overall_ranking") or []) if isinstance(item, dict)]
    best_for = plan_dict.get("best_for") or {}
    decision_context = plan_dict.get("decision_context") or {}
    raw_comparison_rows = [item for item in (decision_context.get("raw_comparison_rows") or []) if isinstance(item, dict)]
    raw_ranking_rows = [item for item in (decision_context.get("raw_ranking_rows") or []) if isinstance(item, dict)]
    uncertainty_notes = [str(item) for item in (plan_dict.get("uncertainty_notes") or []) if str(item).strip()]
    forbidden_claims = [str(item) for item in (plan_dict.get("forbidden_claims") or []) if str(item).strip()]
    omitted_targets = [item for item in (plan_dict.get("omitted_targets") or []) if isinstance(item, dict)]

    issues: list[str] = []
    unknown_fields: list[str] = []
    false_fields: list[str] = []
    unsupported_claims: list[str] = []
    comparison_rows = raw_comparison_rows or raw_ranking_rows or selected_targets or overall_ranking

    def fail(code: str, *, recoverable: bool = True) -> dict[str, Any]:
        violations = list(issues)
        if code not in violations:
            violations.insert(0, code)
        return {
            "passed": False,
            "violation": code,
            "failure_code": code,
            "violations": violations,
            "unknown_fields": unknown_fields,
            "false_fields": false_fields,
            "unsupported_claims": unsupported_claims,
            "recoverable": recoverable,
        }

    # Forbidden claims
    for claim in forbidden_claims:
        if claim and claim in response_text:
            issues.append(f"forbidden_claim:{claim}")
            unsupported_claims.append(response_text)
            return fail("forbidden_claim_violation")

    # Shop hallucination / mismatch
    allowed_names = set()
    for item in selected_targets + omitted_targets:
        for key in ("shop_name", "name", "alias"):
            value = str(item.get(key, "")).strip()
            if value:
                allowed_names.add(value)
                if "(" in value:
                    allowed_names.add(value.split("(", 1)[0].strip())
    if "海底捞(牡丹园店)" in response_text and "海底捞(牡丹园店)" not in allowed_names:
        issues.extend(["hallucinated_shop_name", "shop_mismatch"])
        unsupported_claims.append("海底捞(牡丹园店)")
        return fail("hallucinated_shop_name", recoverable=False)

    # Recommendation / comparison ordering
    if answer_type in {"recommendation", "comparison"} and len((overall_ranking or comparison_rows)) >= 2 and not _contains_any(response_text, ["更近", "距离更近", "离得更近"]):
        expected_source = comparison_rows if answer_type == "comparison" and comparison_rows else (overall_ranking or comparison_rows)
        expected_order = [str(item.get("shop_name", "")).strip() for item in expected_source if str(item.get("shop_name", "")).strip()]
        if expected_order:
            if _contains_any(response_text, ["更好", "胜出", "领先", "更占优", "最推荐", "综合来看", "整体来看"]):
                if expected_order[0] not in response_text:
                    issues.append("ranking_changed_by_llm")
                    unsupported_claims.append(response_text)
                    return fail("ranking_changed_by_llm", recoverable=False)
            positions = [(response_text.find(name), name) for name in expected_order if response_text.find(name) >= 0]
            positions.sort(key=lambda item: item[0])
            mentioned_order = [name for _, name in positions]
            if len(mentioned_order) >= 2 and mentioned_order != expected_order[: len(mentioned_order)]:
                issues.append("ranking_changed_by_llm")
                unsupported_claims.append(response_text)
                return fail("ranking_changed_by_llm", recoverable=False)

    if answer_type == "comparison":
        negative_phrases = ["更差", "不如", "更弱", "更少"]
        winner_phrases = ["综合来看", "整体来看", "最推荐", "更好", "胜出", "领先", "更占优"]
        dimension_winners = plan_dict.get("best_for") or {}
        if comparison_rows and _contains_any(response_text, negative_phrases):
            for row in comparison_rows:
                row_coupon = str(row.get("coupon_status", "unknown") or "unknown").lower()
                row_open = str(row.get("open_status", "unknown") or "unknown").lower()
                row_distance = row.get("distance_km")
                if row_coupon == "unknown" or row_open == "unknown" or row_distance is None:
                    issues.extend(["unknown_as_false", "unsupported_comparison_winner"])
                    if row_coupon == "unknown":
                        unknown_fields.append("coupon")
                    if row_open == "unknown":
                        unknown_fields.append("open_status")
                    if row_distance is None:
                        unknown_fields.append("distance")
                    unsupported_claims.append(response_text)
                    return fail("unknown_as_false")
        if _contains_any(response_text, ["优惠", "有券", "券"]) and not dimension_winners.get("省钱"):
            issues.append("unprovided_dimension_winner")
            unsupported_claims.append(response_text)
            return fail("unprovided_dimension_winner", recoverable=False)
        if _contains_any(response_text, ["营业", "开门"]) and not dimension_winners.get("营业状态"):
            issues.append("unprovided_dimension_winner")
            unsupported_claims.append(response_text)
            return fail("unprovided_dimension_winner", recoverable=False)
        if _contains_any(response_text, ["距离", "更近", "近一点"]) and not dimension_winners.get("距离近"):
            issues.append("unprovided_dimension_winner")
            unsupported_claims.append(response_text)
            return fail("unprovided_dimension_winner", recoverable=False)
        if _contains_any(response_text, ["评分", "口碑", "评价"]) and not dimension_winners.get("评分"):
            issues.append("unprovided_dimension_winner")
            unsupported_claims.append(response_text)
            return fail("unprovided_dimension_winner", recoverable=False)
        if _contains_any(response_text, ["更近", "距离更近", "离得更近"]):
            expected_winner = ""
            if comparison_rows:
                ranked_by_distance = [row for row in comparison_rows if row.get("distance_km") is not None]
                if ranked_by_distance:
                    best_row = min(ranked_by_distance, key=lambda row: float(row.get("distance_km") or 0.0))
                    expected_winner = str(best_row.get("shop_name", "") or best_row.get("shop_id", "")).strip()
            if not expected_winner:
                expected_winner = str((best_for.get("距离近") or {}).get("shop_name", "")).strip()
            if expected_winner:
                phrase_index = min(
                    [idx for idx in (response_text.find("更近"), response_text.find("距离更近"), response_text.find("离得更近")) if idx >= 0],
                    default=-1,
                )
                known_names = [str(row.get("shop_name", "") or row.get("shop_id", "")).strip() for row in comparison_rows if str(row.get("shop_name", "") or row.get("shop_id", "")).strip()]
                closest_name = _closest_expected_name(response_text, known_names or [expected_winner], phrase_index)
                if closest_name and closest_name != expected_winner:
                    issues.append("unsupported_comparison_winner")
                    unsupported_claims.append(response_text)
                    return fail("unsupported_comparison_winner")
        if _contains_any(response_text, winner_phrases):
            ranking_source = comparison_rows or overall_ranking
            first_name = str(ranking_source[0].get("shop_name", "")).strip() if ranking_source else ""
            if first_name and first_name not in response_text:
                issues.append("unsupported_comparison_winner")
                unsupported_claims.append(response_text)
                return fail("unsupported_comparison_winner")

    # Shop-specific facets
    target = selected_targets[0] if selected_targets else {}
    target_name = str(target.get("shop_name", "") or target.get("name", "") or "这家店").strip() or "这家店"
    target_coupon = str(target.get("coupon_status", "unknown") or "unknown").lower()
    target_open = str(target.get("open_status", "unknown") or "unknown").lower()
    target_distance = target.get("distance_km")
    target_price = target.get("avg_price")
    target_rating = target.get("rating")
    unknown_facts = {str(item) for item in (target.get("unknown_facts") or [])}
    failed_facts = {str(item) for item in (target.get("failed_facts") or [])}
    factual_points_text = " ".join(str(item) for item in (plan_dict.get("factual_points") or []))

    if "券" in response_text or "优惠" in response_text:
        if target_coupon == "failed" or "coupon" in failed_facts:
            if _contains_any(response_text, ["没有券", "没有优惠券", "无券", "有券"]):
                issues.extend(["tool_failure_as_fact", "unsupported_coupon"])
                unsupported_claims.append(response_text)
                return fail("tool_failure_as_fact")
        if target_coupon == "empty":
            if _contains_any(response_text, ["有券", "优惠券", "可用券"]) and not _contains_any(response_text, ["暂无", "没有", "无券"]):
                issues.append("unsupported_coupon")
                unsupported_claims.append(response_text)
                return fail("unsupported_coupon")
        if target_coupon == "unknown" or "coupon" in unknown_facts:
            if _contains_any(response_text, ["没有券", "无券", "没有优惠券", "暂无优惠券"]):
                issues.extend(["unknown_as_false", "unsupported_coupon"])
                unknown_fields.append("coupon")
                false_fields.append("coupon")
                unsupported_claims.append(response_text)
                return fail("unknown_as_false")

    if ("营业状态为：目前营业中" in factual_points_text or target_open == "open") and not _contains_any(response_text, ["营业中", "正在营业", "正常营业"]):
        if not _contains_any(response_text, ["暂时无法确认", "无法确认", "不确定", "没查到", "暂未拿到"]):
            issues.append("open_status_missing_open_claim")
            return fail("missing_required_evidence")
    if ("营业状态为：目前已打烊" in factual_points_text or target_open == "closed") and not _contains_any(response_text, ["已打烊", "已关门", "不营业"]):
        if not _contains_any(response_text, ["暂时无法确认", "无法确认", "不确定", "没查到", "暂未拿到"]):
            issues.append("open_status_missing_closed_claim")
            return fail("missing_required_evidence")

    if "营业" in response_text or "打烊" in response_text or "开门" in response_text or "关门" in response_text:
        if target_open == "failed" or "open_status" in failed_facts:
            issues.extend(["tool_failure_as_fact", "unsupported_open_status"])
            unsupported_claims.append(response_text)
            return fail("tool_failure_as_fact")
        if target_open == "unknown" or "open_status" in unknown_facts:
            if _contains_any(response_text, ["不营业", "关门", "打烊", "营业中", "正在营业"]):
                issues.extend(["unknown_as_false", "unsupported_open_status"])
                unknown_fields.append("open_status")
                false_fields.append("open_status")
                unsupported_claims.append(response_text)
                return fail("unknown_as_false")
    if _contains_any(response_text, ["距离", "公里", "km", "米", "很近", "很远", "不远", "几分钟"]):
        if target_distance is None or "distance" in unknown_facts:
            if _contains_any(response_text, ["很近", "很远", "不远", "几分钟", "离我很近", "离我很远"]):
                issues.extend(["unknown_as_false", "unsupported_distance"])
                unknown_fields.append("distance")
                false_fields.append("distance")
                unsupported_claims.append(response_text)
                return fail("unknown_as_false")
        elif target_distance is not None and _contains_any(response_text, ["2.5公里", "2.5 km", "2.5千米"]):
            if abs(float(target_distance) - 2.5) > 0.05:
                issues.append("unsupported_distance")
                unsupported_claims.append(response_text)
                return fail("unsupported_distance")

    if _contains_any(response_text, ["人均", "价格", "消费", "元"]):
        if target_price is not None and _contains_any(response_text, ["120元", "120 元"]):
            if abs(float(target_price) - 120.0) > 1.0:
                issues.append("unsupported_price")
                unsupported_claims.append(response_text)
                return fail("unsupported_price")

    if _contains_any(response_text, ["评分", "口碑", "分"]):
        if target_rating is not None and _contains_any(response_text, ["4.2分", "4.2 分"]):
            if abs(float(target_rating) - 4.2) > 0.05:
                issues.append("unsupported_rating")
                unsupported_claims.append(response_text)
                return fail("unsupported_rating")

    if uncertainty_notes:
        if _contains_any(response_text, ["没有券", "肯定没券", "一定关门", "现在不营业", "离我很近", "评分更高"]):
            issues.append("unknown_as_false")
            unsupported_claims.append(response_text)
            return fail("unknown_as_false")

    if omitted_targets and _contains_any(response_text, ["对比了所有", "对比了全部", "分析了全部", "分析了所有"]):
        issues.append("omitted_targets_violation")
        issues.append("all_targets_claim_violation")
        unsupported_claims.append(response_text)
        return fail("omitted_targets_violation")

    return {
        "passed": True,
        "violation": "",
        "failure_code": "",
        "violations": [],
        "unknown_fields": [],
        "false_fields": [],
        "unsupported_claims": [],
        "recoverable": False,
    }
