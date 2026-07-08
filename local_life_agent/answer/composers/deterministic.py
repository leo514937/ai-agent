from __future__ import annotations

from typing import Any

from ...domain.enums import ResponseMode
from ...domain.schemas import DecisionPlan
from ..response_directive import ResponseDirective


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


def _target_name(plan: DecisionPlan) -> str:
    for item in list(getattr(plan, "selected_targets", []) or []) + ([getattr(plan, "main_recommendation", None)] if getattr(plan, "main_recommendation", None) else []):
        item_dict = _to_dict(item)
        name = str(item_dict.get("shop_name", "") or item_dict.get("alias", "") or "").strip()
        if name:
            return name
    return "这家店"


def _shop_name(item: Any) -> str:
    item_dict = _to_dict(item)
    return str(item_dict.get("shop_name", "") or item_dict.get("alias", "") or item_dict.get("shop_id", "") or "").strip()


def _unique_names(items: list[Any], *, limit: int | None = None) -> list[str]:
    names: list[str] = []
    for item in items:
        name = _shop_name(item)
        if name and name not in names:
            names.append(name)
        if limit is not None and len(names) >= limit:
            break
    return names


def _format_facets(item: Any) -> list[str]:
    item_dict = _to_dict(item)
    parts: list[str] = []
    open_status = str(item_dict.get("open_status", "") or "").strip().lower()
    if open_status in {"open", "opened"}:
        parts.append("营业中")
    elif open_status in {"closed", "close"}:
        parts.append("已打烊")
    coupon_status = str(item_dict.get("coupon_status", "") or "").strip().lower()
    coupon_titles = [str(v).strip() for v in (item_dict.get("coupon_titles") or []) if str(v).strip()]
    if coupon_titles:
        parts.append(f"券：{'、'.join(coupon_titles[:3])}")
    elif coupon_status in {"has_coupon", "grounded"}:
        parts.append("有券")
    elif coupon_status == "empty":
        parts.append("暂无可用优惠券")
    distance_km = item_dict.get("distance_km")
    if distance_km is not None:
        distance_text = f"距离约 {distance_km} 公里"
        eta_minutes = item_dict.get("eta_minutes")
        if eta_minutes is not None:
            distance_text += f"，预计 {eta_minutes} 分钟"
        parts.append(distance_text)
    rating = item_dict.get("rating")
    if rating is not None:
        parts.append(f"评分 {rating}")
    avg_price = item_dict.get("avg_price")
    if avg_price is not None:
        parts.append(f"人均约 {avg_price} 元")
    reason = str(item_dict.get("reason") or item_dict.get("summary") or "").strip()
    if reason:
        parts.append(reason)
    return parts


def _extract_ordered_items(plan: DecisionPlan, *, keys: tuple[str, ...] = ("overall_ranking", "selected_targets", "candidate_summaries")) -> list[Any]:
    for key in keys:
        items = list(getattr(plan, key, []) or [])
        if items:
            return items
    return []


def _format_ranked_shop_lines(items: list[Any], *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items[:limit], start=1):
        name = _shop_name(item) or f"候选{index}"
        facets = _format_facets(item)
        if facets:
            lines.append(f"第{index}位 {name}：{'；'.join(facets)}")
        else:
            lines.append(f"第{index}位 {name}")
    return lines


def _preserved_ranking_notice(plan: DecisionPlan) -> str:
    ranking = _extract_ordered_items(plan, keys=("overall_ranking", "selected_targets"))
    names = _unique_names(ranking, limit=3)
    if names:
        return "；".join(names)
    return ""


def _stage_summary(stage: Any, index: int) -> str:
    stage_dict = _to_dict(stage)
    query = str(stage_dict.get("candidate_query") or stage_dict.get("query") or "").strip()
    status = str(stage_dict.get("status") or "planned").strip() or "planned"
    stage_type = str(stage_dict.get("stage_type") or stage_dict.get("category") or f"阶段{index}").strip()
    pieces = [f"{stage_type}"]
    if query:
        pieces.append(query)
    pieces.append(f"状态：{status}")
    return "，".join(pieces)


class DirectResponseComposer:
    _POLICY_TEXT = {
        "general": ("general", "你好，我可以帮你查商家营业状态、距离、优惠券、评价摘要和人均价格。"),
        "direct_response": ("general", "你好，我可以帮你查商家营业状态、距离、优惠券、评价摘要和人均价格。"),
        "chat": ("general", "你好，我可以帮你查商家营业状态、距离、优惠券、评价摘要和人均价格。"),
        "capability": ("general", "我可以帮你处理本地生活查询，比如营业状态、距离、优惠券、评价摘要和人均价格；暂不支持 RAG、交易、下单、支付、退款和预约。"),
        "unsafe": ("error", "出于安全考虑，我不能继续处理这个请求。"),
        "out_of_scope": ("error", "这个请求超出我当前可支持的本地生活能力，我可以继续帮你处理商家查询类问题。"),
        "invalid": ("clarification", "我没太理解你的意思，可以换个更具体的说法吗？"),
        "forbidden": ("error", "这个请求包含当前不支持或受限的能力，我不能继续处理。"),
    }

    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else _to_dict(plan)
        policy_key = str((context or {}).get("policy_key") or getattr(plan, "fallback_template_type", "") or plan_dict.get("answer_type") or "out_of_scope").strip()
        answer_type, text = self._POLICY_TEXT.get(policy_key, self._POLICY_TEXT["out_of_scope"])
        return ResponseDirective(
            answer_text=text,
            answer_type=answer_type,
            response_mode=ResponseMode.DIRECT.value,
            fallback_reason=str(fallback_reason or plan_dict.get("fallback_reason") or ""),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or plan_dict.get("fallback_template_type") or ""),
            metadata={"policy_key": policy_key},
        )


class ClarificationComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        context = context or {}
        pending = _to_dict(context.get("pending_clarification"))
        if pending:
            try:
                from ...target.clarification import format_pending_prompt

                text = format_pending_prompt(pending)
            except Exception:
                text = "店名有点模糊，请提供完整店名。"
        else:
            text = str(context.get("clarification_text") or plan.required_disclaimers[0] if getattr(plan, "required_disclaimers", None) else "请提供更具体的信息，我再继续帮你处理。").strip()
        if not text:
            text = "请提供更具体的信息，我再继续帮你处理。"
        return ResponseDirective(
            answer_text=text,
            answer_type="clarification",
            response_mode=ResponseMode.CLARIFY.value,
            fallback_reason=str(fallback_reason or getattr(plan, "fallback_template_type", "") or "clarification"),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or "clarification"),
        )


class SystemFallbackComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        context = context or {}
        reason = str(fallback_reason or context.get("fallback_reason") or getattr(plan, "fallback_template_type", "") or "system_fallback").strip()
        text = str(
            context.get("fallback_text")
            or "抱歉，暂时无法处理您的请求，请稍后再试。"
        ).strip()
        if not text:
            text = "抱歉，暂时无法处理您的请求，请稍后再试。"
        if plan.unknown_facets or plan.failed_facets or plan.partial_fields:
            text = "；".join([text, "部分信息暂时无法确认。"])
        return ResponseDirective(
            answer_text=text,
            answer_type="error",
            response_mode=ResponseMode.FALLBACK.value,
            fallback_reason=reason,
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or "system_fallback"),
        )


class SingleShopFactComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else _to_dict(plan)
        target_name = _target_name(plan)
        selected_targets = [item for item in (plan_dict.get("selected_targets") or []) if isinstance(item, dict)]
        target = selected_targets[0] if selected_targets else {}
        grounded_facts = _to_dict(plan_dict.get("grounded_facts"))
        facet_statuses = _to_dict(plan_dict.get("facet_statuses"))
        uncertainty_notes = [str(item).strip() for item in (plan_dict.get("uncertainty_notes") or []) if str(item).strip()]
        factual_points = [str(item).strip() for item in (plan_dict.get("factual_points") or []) if str(item).strip()]

        snippets: list[str] = []

        open_status = str(grounded_facts.get("open_status") or target.get("open_status") or "").strip().lower()
        if open_status in {"open", "opened"}:
            snippets.append("目前营业中")
        elif open_status in {"closed", "close"}:
            snippets.append("当前未营业")
        elif facet_statuses.get("open_status") in {"unknown", "failed", "partial"}:
            uncertainty_notes.append("营业状态暂时无法确认")

        coupon_titles = [str(item).strip() for item in (grounded_facts.get("coupon_titles") or target.get("coupon_titles") or []) if str(item).strip()]
        coupon_count = grounded_facts.get("coupon_count")
        coupon_status = str(target.get("coupon_status") or facet_statuses.get("coupon") or "").strip().lower()
        if coupon_titles:
            snippets.append(f"有券：{'、'.join(coupon_titles[:3])}")
        else:
            coupon_count_num: int | None = None
            if coupon_count not in (None, ""):
                try:
                    coupon_count_num = int(float(coupon_count))
                except Exception:
                    coupon_count_num = None
            if coupon_count_num is not None and coupon_count_num > 0:
                snippets.append(f"当前查到 {coupon_count_num} 张优惠券")
            elif coupon_status == "empty":
                snippets.append("当前暂无可用优惠券")
            elif facet_statuses.get("coupon") in {"unknown", "failed", "partial"}:
                uncertainty_notes.append("优惠情况暂时无法确认")

        distance_km = grounded_facts.get("distance_km")
        eta_minutes = grounded_facts.get("eta_minutes")
        if distance_km is not None:
            distance_text = f"距离约 {distance_km} 公里"
            if eta_minutes is not None:
                distance_text += f"，预计 {eta_minutes} 分钟"
            snippets.append(distance_text)
        elif facet_statuses.get("distance") in {"unknown", "failed", "partial"}:
            uncertainty_notes.append("距离暂时无法确认")

        rating = grounded_facts.get("rating")
        if rating is None:
            rating = target.get("rating")
        if rating is not None:
            snippets.append(f"评分为 {rating}")

        avg_price = grounded_facts.get("avg_price")
        if avg_price is None:
            avg_price = target.get("avg_price") or target.get("price")
        if avg_price is not None:
            snippets.append(f"人均约 {avg_price} 元")

        if not snippets and factual_points:
            snippets.extend(factual_points[:2])

        if snippets:
            text = f"{target_name}：" + "；".join(snippets) + "。"
        elif uncertainty_notes:
            text = f"{target_name}的信息暂时还不完整，我目前只能确认部分内容。"
        else:
            text = f"{target_name}的信息我已经按当前查询结果整理好了。"

        if uncertainty_notes:
            text = f"{text} {'；'.join(dict.fromkeys(uncertainty_notes))}"

        return ResponseDirective(
            answer_text=text,
            answer_type="single_shop",
            response_mode=ResponseMode.ANSWER.value,
            fallback_reason=str(fallback_reason or getattr(plan, "fallback_template_type", "") or ""),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or ""),
        )


class RecommendationComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        context = context or {}
        ranking_items = _extract_ordered_items(plan, keys=("overall_ranking", "selected_targets", "candidate_summaries"))
        ranking_lines = _format_ranked_shop_lines(ranking_items, limit=5)
        if not ranking_lines and getattr(plan, "selected_targets", None):
            ranking_lines = _format_ranked_shop_lines(list(getattr(plan, "selected_targets", []) or []), limit=5)
        best_for = _to_dict(getattr(plan, "best_for", {}) or {})
        uncertainty_notes = [str(item).strip() for item in (getattr(plan, "uncertainty_notes", []) or []) if str(item).strip()]
        factual_points = [str(item).strip() for item in (getattr(plan, "factual_points", []) or []) if str(item).strip()]

        parts: list[str] = []
        if ranking_lines:
            parts.append("推荐顺序如下：")
            parts.extend(ranking_lines)
        else:
            parts.append("当前结果不足以形成稳定推荐。")

        if best_for:
            detail_bits: list[str] = []
            for key, value in best_for.items():
                value_dict = _to_dict(value)
                name = _shop_name(value_dict) or _shop_name(value)
                reason = str(value_dict.get("reason") or value_dict.get("summary") or "").strip()
                if name and reason:
                    detail_bits.append(f"{key}：{name}（{reason}）")
                elif name:
                    detail_bits.append(f"{key}：{name}")
            if detail_bits:
                parts.append("；".join(detail_bits))

        if factual_points:
            parts.append("；".join(factual_points[:2]))
        if uncertainty_notes:
            parts.append("；".join(dict.fromkeys(uncertainty_notes)))

        text = " ".join(parts).strip()
        if not text:
            text = "当前结果不足以形成稳定推荐。"

        return ResponseDirective(
            answer_text=text,
            answer_type="recommendation",
            response_mode=ResponseMode.ANSWER.value,
            fallback_reason=str(fallback_reason or getattr(plan, "fallback_template_type", "") or "recommendation"),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or "recommendation"),
            metadata={
                "policy_key": "recommendation",
                "ranking_preserved": bool(getattr(plan, "ranking_preserved", True)),
                "ranking_order": _unique_names(ranking_items, limit=5),
                "fallback_reason": str(fallback_reason or ""),
                "requested_mode": str(context.get("response_mode") or ""),
            },
        )


class ComparisonComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        context = context or {}
        comparison_items = _extract_ordered_items(plan, keys=("selected_targets", "overall_ranking", "candidate_summaries"))
        ranking_names = _unique_names(comparison_items, limit=5)
        selected_targets = [item for item in (getattr(plan, "selected_targets", []) or []) if _shop_name(item)]
        best_for = _to_dict(getattr(plan, "best_for", {}) or {})
        uncertainty_notes = [str(item).strip() for item in (getattr(plan, "uncertainty_notes", []) or []) if str(item).strip()]
        comparison_support_status = str(getattr(plan, "comparison_support_status", "") or "").strip().lower()
        statistical_winner = _to_dict(getattr(plan, "statistical_winner", {}) or {})
        winner_name = _shop_name(statistical_winner)
        winner_reason = str(
            statistical_winner.get("reason")
            or statistical_winner.get("winner_reason")
            or statistical_winner.get("summary")
            or ""
        ).strip()
        winner_uncertainty_note = str(getattr(plan, "winner_uncertainty_note", "") or "").strip()

        parts: list[str] = []
        if ranking_names:
            parts.append(f"当前对比顺序：{' > '.join(ranking_names)}。")
        elif selected_targets:
            parts.append(f"当前对比了 {len(selected_targets)} 家店。")
        else:
            parts.append("当前对比信息还不完整。")

        if winner_name:
            if winner_reason:
                parts.append(f"整体赢家：{winner_name}（{winner_reason}）")
            else:
                parts.append(f"整体赢家：{winner_name}")
        elif winner_uncertainty_note:
            parts.append(winner_uncertainty_note)
        elif len(ranking_names) >= 2:
            parts.append("当前还没有足够证据确认唯一赢家，只能先看维度差异。")

        if best_for:
            dimension_bits: list[str] = []
            for dimension, value in best_for.items():
                value_dict = _to_dict(value)
                name = _shop_name(value_dict) or _shop_name(value)
                reason = str(value_dict.get("reason") or value_dict.get("summary") or "").strip()
                if name and reason:
                    dimension_bits.append(f"{dimension}：{name}（{reason}）")
                elif name:
                    dimension_bits.append(f"{dimension}：{name}")
            if dimension_bits:
                parts.append("维度结论：" + "；".join(dimension_bits))

        if comparison_support_status and comparison_support_status not in {"grounded", "supported", "ok", "sufficient"}:
            if not winner_name:
                parts.append("当前证据还不足以改变现有排序或直接宣布赢家。")
        if uncertainty_notes:
            parts.append("；".join(dict.fromkeys(uncertainty_notes)))

        text = " ".join(parts).strip()
        if not text:
            text = "当前对比信息还不完整。"

        return ResponseDirective(
            answer_text=text,
            answer_type="comparison",
            response_mode=ResponseMode.COMPARISON.value,
            fallback_reason=str(fallback_reason or getattr(plan, "fallback_template_type", "") or "comparison"),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or "comparison"),
            metadata={
                "policy_key": "comparison",
                "ranking_preserved": bool(getattr(plan, "ranking_preserved", True)),
                "ranking_order": ranking_names,
                "comparison_support_status": comparison_support_status,
                "statistical_winner": statistical_winner,
                "winner_provenance": _to_dict(getattr(plan, "winner_provenance", {}) or {}),
                "fallback_reason": str(fallback_reason or ""),
                "requested_mode": str(context.get("response_mode") or ""),
            },
        )


class ExplorationPlanComposer:
    def compose(self, plan: DecisionPlan, *, trace_id: str = "", fallback_reason: str = "", context: dict[str, Any] | None = None) -> ResponseDirective:
        context = context or {}
        stages = list(getattr(plan, "exploration_stages", []) or [])
        stage_queries = [str(item).strip() for item in (getattr(plan, "stage_queries", []) or []) if str(item).strip()]
        stage_statuses = [str(item).strip().lower() for item in (getattr(plan, "stage_statuses", []) or []) if str(item).strip()]
        uncertainty_notes = [str(item).strip() for item in (getattr(plan, "uncertainty_notes", []) or []) if str(item).strip()]

        parts: list[str] = []
        if stage_queries:
            parts.append("我会按阶段推进：")
            parts.append(" -> ".join(stage_queries))
        elif stages:
            parts.append("我会按阶段推进这次探索。")
        else:
            parts.append("当前探索计划还不完整。")

        if stages:
            stage_lines = [_stage_summary(stage, index + 1) for index, stage in enumerate(stages[:4])]
            if stage_lines:
                parts.append("阶段拆分：" + "；".join(stage_lines))

        if any(status in {"unknown", "failed", "empty", "partial"} for status in stage_statuses):
            parts.append("其中有些阶段的信息还不完整，我会先保留不确定性。")
        if uncertainty_notes:
            parts.append("；".join(dict.fromkeys(uncertainty_notes)))

        text = " ".join(parts).strip()
        if not text:
            text = "当前探索计划还不完整。"

        return ResponseDirective(
            answer_text=text,
            answer_type="exploration_plan",
            response_mode=ResponseMode.EXPLORATION_PLAN.value,
            fallback_reason=str(fallback_reason or getattr(plan, "fallback_template_type", "") or "exploration_plan"),
            trace_id=trace_id,
            final_response=text,
            preview_text=text,
            answer_source="deterministic_composer",
            fallback_template_type=str(getattr(plan, "fallback_template_type", "") or "exploration_plan"),
            metadata={
                "policy_key": "exploration_plan",
                "stage_queries": stage_queries,
                "stage_statuses": stage_statuses,
                "fallback_reason": str(fallback_reason or ""),
                "requested_mode": str(context.get("response_mode") or ""),
            },
        )


def compose_deterministic_response(
    plan: DecisionPlan,
    *,
    trace_id: str = "",
    fallback_reason: str = "",
    context: dict[str, Any] | None = None,
) -> ResponseDirective:
    answer_type = str(getattr(plan, "answer_type", "") or "").strip()
    fallback_template_type = str(getattr(plan, "fallback_template_type", "") or "").strip()
    context = context or {}
    if answer_type == "clarification" or fallback_template_type == "clarification" or context.get("response_mode") == ResponseMode.CLARIFY.value:
        return ClarificationComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type in {"error"} or fallback_template_type in {"multi_facet_failed", "multi_facet_empty", "multi_facet_circuit_open", "system_fallback"} or context.get("response_mode") == ResponseMode.FALLBACK.value:
        return SystemFallbackComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type in {"single_shop", "single_shop_query", "coupon", "open_status", "distance"}:
        return SingleShopFactComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type == "recommendation" or fallback_template_type == "recommendation":
        return RecommendationComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type == "comparison" or fallback_template_type == "comparison":
        return ComparisonComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type in {"exploration_plan", "exploration"} or fallback_template_type in {"exploration_plan", "exploration"}:
        return ExplorationPlanComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    if answer_type in {"general", "chat", "capability", "out_of_scope", "unsafe", "invalid", "forbidden"}:
        return DirectResponseComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
    return SystemFallbackComposer().compose(plan, trace_id=trace_id, fallback_reason=fallback_reason, context=context)
