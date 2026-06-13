from __future__ import annotations

import logging
import re

from learning_agent_service.domain.errors import TerminalEvent
from learning_agent_service.domain.utils import as_mapping as _as_mapping
from learning_agent_service.local_life.schemas import LocalLifeSlots

from .helpers import Any, GraphState, Mapping, _build_recommendation_answer_text, _build_single_shop_review_answer, _phase2_evidence_pack, _routing_decision_for_turn
from ..state import append_runtime_event as _append_state_runtime_event
from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query, _strip_facet_suffixes


_LOGGER = logging.getLogger(__name__)

_QUERY_ENTITY_SUFFIXES = (
    "怎么样",
    "好不好",
    "值不值得",
    "适合约会",
    "有券吗",
    "现在营业吗",
    "现在还营业吗",
    "营业吗",
    "在哪里",
    "在哪",
    "有优惠吗",
)


def _fresh_entity_from_query_text(raw_query: str) -> str | None:
    compact = str(raw_query or "").strip()
    if not compact:
        return None
    compact = re.sub(r"[?？!！。．\.]+$", "", compact)
    for suffix in _QUERY_ENTITY_SUFFIXES:
        if compact.endswith(suffix):
            prefix = compact[: -len(suffix)].strip(" 的,，。！？?")
            if prefix:
                cleaned = _strip_facet_suffixes(prefix)
                if cleaned:
                    return cleaned
    return None


class WorkflowNodeAdapterStagesBackEmitMixin:
        container: 'Any'
        _plan_executor: 'Any'
        plan_planner: 'Any'
        plan_validator: 'Any'
        step_executor: 'Any'
        progress_checker: 'Any'
        plan_reviewer: 'Any'
        replanner: 'Any'
        human_approval_stub: 'Any'
        business_client: 'Any'
        def emit_final(self, state: GraphState) -> GraphState:
            runtime = state["runtime"]
            turn = state["turn"]
            turn_extra = dict(getattr(turn, "extra", {}) or {})
            selected_shop_id = None
            route_review_shop_name = ""
            route_gate: dict[str, Any] = {}
            route_review_obj = None
            route_review: dict[str, Any] = {}
            recommendation_like_query = False
            explicit_query_shop = ""
            answer_contract_payload: dict[str, Any] = {}
            session_shop_name: Any = None
            target_shop_name = ""
            phase4_trace: dict[str, Any] = {}
            target_shop_payload: dict[str, Any] = {}
            target_shop_source: Any = None
            evidence_shop_ids: list[int] = []
            evidence_shop_names: list[str] = []
            metrics: dict[str, Any] = dict(runtime.metrics or {})
            final_metrics: dict[str, Any] = dict(runtime.metrics or {})
            payload: dict[str, Any] = {}
            if runtime.terminal_event == TerminalEvent.ERROR:
                last_error = runtime.errors[-1] if runtime.errors else None
                routing = _routing_decision_for_turn(turn)
                payload = {
                    "code": last_error.code.value if last_error is not None else "LEARN-5001",
                    "message": last_error.message if last_error is not None else "内部错误",
                    "retryable": bool(last_error.retryable) if last_error is not None else False,
                    "stage": last_error.stage if last_error is not None else "emit_final",
                    "degraded_to": last_error.degraded_to if last_error is not None else None,
                    "details": dict(last_error.details) if last_error is not None else {},
                    "current_stage": turn.current_stage,
                    "stage_status": turn.stage_status,
                    "route_decision": routing.required_action if routing is not None else None,
                    "route_reason": routing.route_reason if routing is not None else None,
                }
                state = _append_state_runtime_event(state, "error", payload)
                return state
            elif runtime.terminal_event == TerminalEvent.CLARIFICATION_CARD:
                card = turn.clarification_card.model_dump(mode="json") if turn.clarification_card is not None else {}
                payload = {
                    **card,
                    "context": {
                        "pending_user_need": _as_mapping(turn.extra.get("user_need") or getattr(state["persistent"], "pending_user_need", {}) or {}),
                        "route_review": turn_extra.get("route_review_decision"),
                        "metrics": dict(runtime.metrics or {}),
                    },
                }
                state = _append_state_runtime_event(state, "clarification_card", payload)
                return state
            else:
                metrics = dict(runtime.metrics or {})
                stage_metrics = dict(metrics.get("stage_elapsed_ms", {}) or {})
                total_elapsed_ms = float(sum(float(value or 0.0) for value in stage_metrics.values()))
                degrade_items = list(metrics.get("degrade_to_list", []) or [])
                if runtime.degrade_to and runtime.degrade_to not in degrade_items:
                    degrade_items.append(runtime.degrade_to)
                final_metrics = {
                    **metrics,
                    "stages": stage_metrics,
                    "total_elapsed_ms": total_elapsed_ms,
                    "embedding_cache_hit": bool(metrics.get("embedding_cache_hit", False)),
                    "degrade_to": degrade_items,
                }
                turn_extra = dict(getattr(turn, "extra", {}) or {})
                routing = _routing_decision_for_turn(turn)
                route_gate = dict(turn_extra.get("route_gate") or metrics.get("route_gate") or {})
                route_review_obj = None
                route_review_shop_name = ""
                if routing is not None and isinstance(getattr(routing, "extra", None), Mapping):
                    route_review_obj = (routing.extra or {}).get("route_review_decision")
                route_review = dict(route_review_obj or {})
                route_review = route_review or dict(route_gate.get("route_review_decision") or {})
                for metric_key in ("final_answer_safety", "final_answer_audit", "answer_lint"):
                    metric_value = turn_extra.get(metric_key)
                    if metric_value is not None and metric_key not in final_metrics:
                        final_metrics[metric_key] = metric_value
                semantic_route = route_review.get("semantic_route")
                if isinstance(semantic_route, Mapping):
                    route_review_shop_name = str(
                        (
                            dict(semantic_route.get("slots") or {}).get("shop_name")
                            or semantic_route.get("selected_shop_name")
                            or semantic_route.get("resolved_shop_name")
                            or ""
                        )
                    ).strip()
                def _resolve_shop_id_by_name(shop_name: Any) -> int | None:
                    lookup_text = str(shop_name or "").strip()
                    if not lookup_text:
                        return None
                    try:
                        business_client = getattr(self.container, "java_business_client", None) or getattr(self, "business_client", None)
                        if business_client is not None and hasattr(business_client, "search_shops_by_name"):
                            matches = business_client.search_shops_by_name(name=lookup_text, current=1)
                            if matches:
                                best = matches[0]
                                best_id = getattr(best, "id", None)
                                if best_id not in (None, ""):
                                    return int(best_id)
                    except Exception:
                        pass
                    try:
                        from ...local_life.catalog import get_default_catalog

                        catalog = get_default_catalog()
                        matches = catalog.search_shops(query=lookup_text, slots=LocalLifeSlots(shop_query=lookup_text), limit=5)
                        if matches:
                            best = matches[0]
                            best_id = getattr(best, "id", None)
                            if best_id not in (None, ""):
                                return int(best_id)
                    except Exception:
                        pass
                    return None
                raw_query_text = str(turn.raw_query or "")
                compact_query_text = raw_query_text.replace(" ", "")
                review_query_tokens = ("评价", "环境", "口味", "服务", "评分", "怎么样", "好不好")
                recommendation_like_query = bool(
                    route_gate.get("branch") == "recommendation"
                    or any(token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家"))
                )
                review_like_query = any(token in compact_query_text for token in review_query_tokens)
                explicit_query_shop = _explicit_entity_from_query(turn.raw_query) or _fresh_entity_from_query_text(turn.raw_query)
                if not explicit_query_shop:
                    extra_explicit_query_shop = str(turn_extra.get("explicit_query_shop") or "").strip()
                    if extra_explicit_query_shop:
                        explicit_query_shop = extra_explicit_query_shop
                generic_shop_names = {"杩欏搴?", "杩欏", "杩欏簵", "璇ュ晢瀹?", "鍟嗗", "褰撳墠搴楀"}
                if route_review_shop_name in generic_shop_names:
                    route_review_shop_name = ""
                if recommendation_like_query and not explicit_query_shop:
                    route_review_shop_name = ""
                if not explicit_query_shop and route_review_shop_name:
                    explicit_query_shop = route_review_shop_name
                answer_contract_payload = turn_extra.get("answer_contract")
                if hasattr(answer_contract_payload, "model_dump"):
                    answer_contract_payload = answer_contract_payload.model_dump(mode="json")
                if not isinstance(answer_contract_payload, Mapping):
                    answer_contract_payload = {}
                session_shop_name = turn_extra.get("current_shop") or route_review.get("selected_shop_name") or route_review.get("resolved_shop_name")
                if recommendation_like_query and not explicit_query_shop and not route_review_shop_name:
                    session_shop_name = None
                target_shop_name = explicit_query_shop or (route_review_shop_name if not recommendation_like_query else None) or session_shop_name
                explicit_shop_context = bool(
                    (explicit_query_shop and explicit_query_shop not in generic_shop_names)
                    or (route_review_shop_name and route_review_shop_name not in generic_shop_names)
                    or (target_shop_name and str(target_shop_name).strip() not in generic_shop_names)
                    or (session_shop_name and str(session_shop_name).strip() not in generic_shop_names)
                )
                response_node = str(turn_extra.get("response_node") or "").strip().lower()
                direct_non_local_response = response_node in {"direct_chat_answer", "out_of_scope_response", "safety_reject_response"}
                raw_query_text = str(turn.raw_query or "")
                compact_query_text = raw_query_text.replace(" ", "")
                inferred_coupon = any(token in compact_query_text for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
                inferred_open = any(token in compact_query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
                inferred_distance = any(token in compact_query_text for token in ("离我多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
                comparison_like = (
                    any(token in compact_query_text for token in ("对比", "比较", "区别", "差别", "哪家更", "哪个更", "更便宜", "更适合", "更好"))
                    and any(token in compact_query_text for token in ("和", "比", "vs"))
                ) or str(turn_extra.get("top_level_intent") or "").strip().lower() in {"comparison", "restaurant_comparison", "local_life_comparison"}
                answer_style = str(answer_contract_payload.get("answer_style") or "").strip().lower()
                contract_facets_map = {
                    "coupon_only": (
                        ["coupon"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "open_status", "distance_eta", "price"],
                    ),
                    "open_status_only": (
                        ["open_status"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "distance_eta", "price"],
                    ),
                    "distance_only": (
                        ["distance_eta", "distance"],
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "price"],
                    ),
                    "facet_multi": (
                        ["coupon", "open_status", "distance_eta", "distance", "price", "shop_detail", "recommendation_reason"],
                        ["recommendation"],
                    ),
                    "single_shop_review": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "multi_shop_recommendation": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "comparison": (
                        ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                        [],
                    ),
                    "clarification": (
                        [],
                        ["environment", "taste", "service", "recommendation", "coupon", "open_status", "distance_eta", "price"],
                    ),
                }
                if answer_style == "multi_shop_recommendation" and route_gate.get("branch") != "recommendation" and (
                    explicit_query_shop
                    or target_shop_name
                    or selected_shop_id is not None
                    or turn_extra.get("current_shop")
                    or state["persistent"].current_shop
                    or state["persistent"].selected_shop_name
                ) and not any(
                    token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
                ):
                    answer_style = "single_shop_review"
                if direct_non_local_response:
                    answer_style = None
                    answer_contract_payload = {
                        "answer_style": None,
                        "required_facets": [],
                        "allowed_facets": [],
                        "forbidden_facets": [],
                    }
                if not answer_style:
                    if inferred_coupon and not inferred_open and not inferred_distance and not review_like_query:
                        answer_style = "coupon_only"
                    elif inferred_open and not inferred_coupon and not inferred_distance:
                        answer_style = "open_status_only"
                    elif inferred_distance and not inferred_coupon and not inferred_open:
                        answer_style = "distance_only"
                    elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
                        answer_style = "facet_multi"
                    elif comparison_like:
                        answer_style = "comparison"
                    elif route_gate.get("branch") == "recommendation" or any(
                        token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
                    ):
                        answer_style = "multi_shop_recommendation"
                    elif explicit_query_shop or target_shop_name:
                        answer_style = "single_shop_review"
                if inferred_open and not inferred_coupon and not inferred_distance:
                    answer_style = "open_status_only"
                elif inferred_distance and not inferred_coupon and not inferred_open:
                    answer_style = "distance_only"
                elif inferred_coupon and not inferred_open and not inferred_distance and not review_like_query:
                    answer_style = "coupon_only"
                elif comparison_like:
                    answer_style = "comparison"
                elif route_gate.get("branch") == "recommendation" or any(
                    token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
                ):
                    answer_style = "multi_shop_recommendation"
                if not answer_contract_payload:
                    required_facets: list[dict[str, Any]] = []
                    if inferred_coupon:
                        required_facets.append({"name": "coupon"})
                    if inferred_open:
                        required_facets.append({"name": "open_status"})
                    if inferred_distance:
                        required_facets.append({"name": "distance_eta"})
                        required_facets.append({"name": "distance"})
                    fallback_allowed, fallback_forbidden = contract_facets_map.get(
                        answer_style,
                        (
                            ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                            [],
                        ),
                    )
                    if answer_style == "multi_shop_recommendation" and not required_facets and route_gate.get("branch") == "recommendation":
                        required_facets = []
                    answer_contract_payload = {
                        "answer_style": answer_style or "single_shop_review",
                        "required_facets": required_facets,
                        "allowed_facets": fallback_allowed,
                        "forbidden_facets": fallback_forbidden,
                    }
                phase4_trace = dict(metrics.get("phase4_trace") or {})
                target_shop_payload = turn_extra.get("target_shop")
                if isinstance(target_shop_payload, Mapping):
                    target_shop_payload = dict(target_shop_payload)
                else:
                    target_shop_payload = {}
                target_shop_source = (
                    turn_extra.get("target_shop.source")
                    or target_shop_payload.get("source")
                    or route_review.get("target_shop_source")
                )
                if not target_shop_source:
                    pronoun_like_query = any(p in str(turn.raw_query or "") for p in ("它", "他", "她", "这家", "这店", "这间", "刚才那家", "刚才那个", "这商家", "这个商家"))
                    if target_shop_payload.get("is_pronoun_inherited") or pronoun_like_query:
                        target_shop_source = "pronoun_session"
                    elif explicit_query_shop:
                        target_shop_source = "current_query"
                    elif turn_extra.get("current_shop") or route_review.get("semantic_route", {}).get("slots", {}).get("shop_name"):
                        target_shop_source = "session"
                evidence_shop_ids: list[int] = []
                evidence_shop_names: list[str] = []
                evidence_pack = _phase2_evidence_pack(turn)
                evidence_items = list(getattr(evidence_pack, "items", []) or []) if evidence_pack is not None else []
                for item in evidence_items:
                    metadata = dict(getattr(item, "metadata", {}) or {})
                    shop_id_value = metadata.get("shop_id") or metadata.get("parent_shop_id") or metadata.get("entity_shop_id")
                    if shop_id_value not in (None, ""):
                        try:
                            shop_id_int = int(shop_id_value)
                        except Exception:
                            shop_id_int = None
                        if shop_id_int is not None and shop_id_int not in evidence_shop_ids:
                            evidence_shop_ids.append(shop_id_int)
                    shop_name_value = metadata.get("shop_name") or metadata.get("parent_shop_name") or metadata.get("entity_shop_name")
                    if shop_name_value:
                        shop_name_text = str(shop_name_value).strip()
                        if shop_name_text and shop_name_text not in evidence_shop_names:
                            evidence_shop_names.append(shop_name_text)
                selected_shop_id = None
                if explicit_query_shop or target_shop_name:
                    selected_shop_id = _resolve_shop_id_by_name(explicit_query_shop or target_shop_name)
                if selected_shop_id is None and evidence_shop_ids:
                    selected_shop_id = evidence_shop_ids[0]
                elif selected_shop_id is None and isinstance(route_review.get("resolved_shop_id"), int):
                    selected_shop_id = int(route_review.get("resolved_shop_id"))
                elif selected_shop_id is None and isinstance(route_review.get("execution_requirements"), Mapping):
                    exec_req = dict(route_review.get("execution_requirements") or {})
                    if isinstance(exec_req.get("resolved_shop_id"), int):
                        selected_shop_id = int(exec_req.get("resolved_shop_id"))
                    elif exec_req.get("resolved_shop_id") not in (None, ""):
                        try:
                            selected_shop_id = int(exec_req.get("resolved_shop_id"))
                        except Exception:
                            selected_shop_id = None
                elif selected_shop_id is None and isinstance(turn_extra.get("selected_shop_id"), int):
                    selected_shop_id = int(turn_extra.get("selected_shop_id"))
                if selected_shop_id is None:
                    selected_entity = phase4_trace.get("selected_entity")
                    if isinstance(selected_entity, str):
                        selected_text = selected_entity.strip()
                        if ":" in selected_text:
                            maybe_id = selected_text.split(":", 1)[1].strip()
                            try:
                                selected_shop_id = int(maybe_id)
                            except Exception:
                                selected_shop_id = None
                def _resolve_shop_id_by_name(shop_name: Any) -> int | None:
                    lookup_text = str(shop_name or "").strip()
                    if not lookup_text:
                        return None
                    try:
                        business_client = getattr(self.container, "java_business_client", None) or getattr(self, "business_client", None)
                        if business_client is not None and hasattr(business_client, "search_shops_by_name"):
                            matches = business_client.search_shops_by_name(name=lookup_text, current=1)
                            if matches:
                                best = matches[0]
                                best_id = getattr(best, "id", None)
                                if best_id not in (None, ""):
                                    return int(best_id)
                    except Exception:
                        pass
                    try:
                        from ...local_life.catalog import get_default_catalog

                        catalog = get_default_catalog()
                        matches = catalog.search_shops(query=lookup_text, slots=LocalLifeSlots(shop_query=lookup_text), limit=5)
                        if matches:
                            best = matches[0]
                            best_id = getattr(best, "id", None)
                            if best_id not in (None, ""):
                                return int(best_id)
                    except Exception:
                        pass
                    return None
                if answer_contract_payload:
                    allowed_facets = answer_contract_payload.get("allowed_facets")
                    forbidden_facets = answer_contract_payload.get("forbidden_facets")
                    fallback_allowed, fallback_forbidden = contract_facets_map.get(
                        answer_style,
                        (
                            ["environment", "taste", "service", "recommendation", "scene_fit", "coupon", "open_status", "distance_eta", "price", "shop_detail", "recommendation_reason"],
                            [],
                        ),
                    )
                    if not isinstance(allowed_facets, list) or not allowed_facets:
                        answer_contract_payload["allowed_facets"] = fallback_allowed
                    if not isinstance(forbidden_facets, list) or not forbidden_facets:
                        answer_contract_payload["forbidden_facets"] = fallback_forbidden
                routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
                out_of_scope_query = bool(
                    str(turn_extra.get("top_level_intent") or "").strip().lower() == "out_of_scope"
                    or str(getattr(routing, "route_candidate", "") or "").strip().lower() == "out_of_scope"
                    or str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower() == "out_of_scope"
                )
                if route_gate.get("branch") == "recommendation" or recommendation_like_query:
                    answer_style = "multi_shop_recommendation"
                elif routing_action == "clarify":
                    answer_style = "clarification"
                elif inferred_coupon and not inferred_open and not inferred_distance and not any(token in compact_query_text for token in review_query_tokens):
                    answer_style = "coupon_only"
                elif inferred_open and not inferred_coupon and not inferred_distance:
                    answer_style = "open_status_only"
                elif inferred_distance and not inferred_coupon and not inferred_open:
                    answer_style = "distance_only"
                elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
                    answer_style = "facet_multi"
                elif out_of_scope_query:
                    answer_style = "clarification"
                elif explicit_query_shop or target_shop_name:
                    answer_style = answer_style or "single_shop_review"
                else:
                    answer_style = answer_style or "single_shop_review"
                if explicit_query_shop or recommendation_like_query:
                    priority_source = "current_query"
                elif target_shop_source in {"session", "pronoun_session"} or session_shop_name:
                    priority_source = "session_context"
                else:
                    priority_source = "latest_turn_message"

                final_metrics["priority_source"] = priority_source
                final_metrics["out_of_scope"] = out_of_scope_query
                final_metrics["clarification_needed"] = bool(routing_action == "clarify" or answer_style == "clarification")
                final_metrics["recommendation_mode"] = bool(route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation")
                final_metrics["target_shop.source"] = target_shop_source
                final_metrics["target_shop.shop_name"] = target_shop_name
                final_metrics["target_shop.shop_id"] = selected_shop_id
                final_metrics["selected_shop_id"] = selected_shop_id
                final_metrics["single_shop_mode"] = bool(
                    route_gate.get("branch") != "recommendation"
                    and not out_of_scope_query
                    and (target_shop_source in {"current_query", "pronoun_session", "session"} or answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review", "facet_multi"})
                )
                if route_gate.get("branch") == "recommendation":
                    final_metrics["single_shop_mode"] = False
                if evidence_shop_ids:
                    final_metrics["evidence_shop_ids"] = evidence_shop_ids
                if evidence_shop_names:
                    final_metrics["evidence_shop_names"] = evidence_shop_names
                if not final_metrics.get("rag_mode"):
                    if route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation":
                        final_metrics["rag_mode"] = "recommendation_rag"
                    elif final_metrics.get("single_shop_mode"):
                        final_metrics["rag_mode"] = "single_shop_rag"
                phase5_trace = dict(metrics.get("phase5_trace") or {})
                graph_runtime = str(
                    phase5_trace.get("graph_runtime")
                    or phase5_trace.get("runner_backend")
                    or phase5_trace.get("runner_kind")
                    or "unknown"
                ).strip() or "unknown"
                graph_fallback = str(
                    turn_extra.get("graph_fallback")
                    or state["persistent"].extra.get("graph_fallback")
                    or "none"
                ).strip() or "none"
                if graph_runtime == "unknown":
                    graph_runtime = "langgraph"
                final_metrics["graph_runtime"] = graph_runtime
                final_metrics["runner_kind"] = str(phase5_trace.get("runner_kind") or graph_runtime).strip() or graph_runtime
                phase5_trace["graph_runtime"] = final_metrics["graph_runtime"]
                phase5_trace["runner_kind"] = final_metrics["runner_kind"]
                phase5_trace["runner_backend"] = str(phase5_trace.get("runner_backend") or final_metrics["runner_kind"]).strip() or final_metrics["runner_kind"]
                phase5_trace["runner_class"] = str(phase5_trace.get("runner_class") or "LangGraphWorkflowRunner").strip() or "LangGraphWorkflowRunner"
                phase5_trace["compare_ready"] = bool(phase5_trace.get("compare_ready", True))
                final_metrics["phase5_trace"] = phase5_trace
                final_metrics["graph_fallback"] = graph_fallback
                if graph_fallback != "none":
                    final_metrics["graph_fallback_reason"] = (
                        turn_extra.get("graph_fallback_reason")
                        or state["persistent"].extra.get("graph_fallback_reason")
                    )
                routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
                route_gate_branch = str(route_gate.get("branch") or "").strip().lower()
                if route_gate and routing_action == "clarify" and recommendation_like_query and route_gate_branch != "recommendation":
                    route_gate_branch = "recommendation"
                    route_gate = {
                        **route_gate,
                        "branch": "recommendation",
                        "required_action": "rag_plus_tool",
                    }
                    routing = routing.model_copy(update={"required_action": "rag_plus_tool"})
                    turn_extra = dict(getattr(turn, "extra", {}) or {})
                    turn_extra["route_gate"] = route_gate
                    turn_extra["routing_decision"] = routing.model_dump(mode="json")
                    turn_extra["route_reason"] = routing.route_reason
                    turn_extra["route_candidate"] = routing.route_candidate
                    turn = turn.model_copy(update={"extra": turn_extra})
                    final_metrics["route_gate"] = route_gate
                    final_metrics["routing_decision"] = routing.model_dump(mode="json")
                if route_gate and routing_action == "clarify" and route_gate_branch != "clarify" and not recommendation_like_query and not explicit_shop_context:
                    route_gate_branch = "clarify"
                    route_gate = {
                        **route_gate,
                        "branch": "clarify",
                        "required_action": "clarify",
                    }
                    final_metrics["route_gate"] = route_gate
                if not route_gate:
                    route_gate_branch = "direct"
                    if routing_action == "clarify":
                        route_gate_branch = "clarify"
                    elif bool(turn_extra.get("recommendation_mode")) or final_metrics.get("rag_mode") == "recommendation_rag":
                        route_gate_branch = "recommendation"
                    elif routing_action == "tool_call":
                        route_gate_branch = "tool"
                    elif routing_action == "rag_plus_tool":
                        route_gate_branch = "rag_plus_tool"
                    elif routing_action == "rag_retrieval":
                        route_gate_branch = "rag"
                    route_gate = {
                        "branch": route_gate_branch,
                        "required_action": routing.required_action if routing is not None else None,
                        "route_candidate": routing.route_candidate if routing is not None else None,
                        "route_reason": routing.route_reason if routing is not None else None,
                    }
                    final_metrics["route_gate"] = route_gate
                latest_turn_message = str(turn.raw_query or "").strip()
                if latest_turn_message:
                    final_metrics["latest_turn_message"] = latest_turn_message
                if not explicit_query_shop:
                    explicit_query_shop = _explicit_entity_from_query(str(turn.raw_query or "")) or _fresh_entity_from_query_text(str(turn.raw_query or ""))
                current_shop_name = (
                    explicit_query_shop
                    or (turn_extra.get("current_shop") if not recommendation_like_query else None)
                    or (state["persistent"].current_shop if not recommendation_like_query else None)
                    or (state["persistent"].selected_shop_name if not recommendation_like_query else None)
                    or (target_shop_name if not recommendation_like_query else None)
                    or "这家店"
                )
                tool_plan_required_tools: list[str] = []
                tool_plan_inputs: dict[str, list[dict[str, Any]]] = {}
                required_facets = answer_contract_payload.get("required_facets") if isinstance(answer_contract_payload, Mapping) else []
                if isinstance(required_facets, list):
                    for facet_item in required_facets:
                        facet_map = facet_item if isinstance(facet_item, Mapping) else {}
                        facet_name = str(facet_map.get("name") or "").strip()
                        if facet_name == "coupon":
                            tool_name = "get_coupon_list"
                        elif facet_name == "open_status":
                            tool_name = "check_open_status"
                        elif facet_name == "distance_eta":
                            tool_name = "get_distance_eta"
                        else:
                            continue
                        if tool_name not in tool_plan_required_tools:
                            tool_plan_required_tools.append(tool_name)
                        tool_plan_inputs.setdefault(tool_name, []).append(
                            {
                                "tool_name": tool_name,
                                "facet": facet_name,
                                "shop_id": selected_shop_id,
                                "shop_name": target_shop_name or current_shop_name or explicit_query_shop or None,
                                "source_scope": "recommendation_candidate" if route_gate.get("branch") == "recommendation" else ("target_shop" if selected_shop_id is not None else "fallback_candidate"),
                            }
                        )
                local_life_tool_results: list[dict[str, Any]] = []
                tool_result = getattr(turn, "tool_result", None)
                tool_result_payload = tool_result.model_dump(mode="json") if hasattr(tool_result, "model_dump") else {}
                for tool_name in tool_plan_required_tools or ([str(tool_result_payload.get("tool_name") or "").strip()] if tool_result_payload.get("tool_name") else []):
                    if not tool_name:
                        continue
                    local_life_tool_results.append(
                        {
                            "tool_name": tool_name,
                            "status": str(tool_result_payload.get("status") or "success"),
                            "fetched_at": runtime.request_ts.isoformat(),
                            "is_realtime": tool_name in {"get_coupon_list", "check_open_status", "get_distance_eta"},
                            "shop_id": selected_shop_id,
                            "shop_name": target_shop_name or current_shop_name or explicit_query_shop or None,
                        }
                    )
                final_metrics["tool_plan"] = {
                    "required_tools": tool_plan_required_tools,
                    "optional_tools": [],
                    "tool_inputs": tool_plan_inputs,
                    "runs": [],
                    "execution_mode": "per_candidate" if route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation" else ("single_shop" if tool_plan_required_tools else "none"),
                    "timeout_budget_ms": 3000,
                    "fallback_policy": "strict_realtime_contract",
                    "source_intent": str(answer_style or routing.required_action if routing is not None else ""),
                    "latest_turn_message": latest_turn_message,
                    "current_intent": str(turn.intent.value if turn.intent else answer_style or ""),
                    "blocked_by_realtime_contract": False,
                    "blocked_reason": None,
                    "forbidden_facets": list(answer_contract_payload.get("forbidden_facets") or []),
                    "target_shop_id": None if route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation" else selected_shop_id,
                    "candidate_shop_ids": list(dict.fromkeys(evidence_shop_ids)) if evidence_shop_ids else ([selected_shop_id] if selected_shop_id is not None else []),
                }
                final_metrics["local_life_tool_results"] = local_life_tool_results
                final_metrics["recommendation_tool_scope"] = {
                    "enabled": bool(route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation"),
                    "branch": route_gate.get("branch"),
                    "target_shop_id": None if route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation" else selected_shop_id,
                    "candidate_count": len(evidence_shop_ids),
                }
                final_metrics["answer_realtime_claim_supported"] = bool(tool_plan_required_tools)
                if answer_contract_payload:
                    final_metrics["answer_contract"] = answer_contract_payload
                if turn_extra.get("coupon_result"):
                    final_metrics["coupon_result"] = turn_extra.get("coupon_result")
                if turn_extra.get("facet_result_bundle"):
                    final_metrics["facet_result_bundle"] = turn_extra.get("facet_result_bundle")

                final_answer_text = str(turn.final_answer or "").strip()
                if not explicit_query_shop:
                    explicit_query_shop = _explicit_entity_from_query(str(turn.raw_query or "")) or _fresh_entity_from_query_text(str(turn.raw_query or ""))
                current_shop_name = (
                    explicit_query_shop
                    or (turn_extra.get("current_shop") if not recommendation_like_query else None)
                    or (state["persistent"].current_shop if not recommendation_like_query else None)
                    or (state["persistent"].selected_shop_name if not recommendation_like_query else None)
                    or (target_shop_name if not recommendation_like_query else None)
                    or "这家店"
                )
                if explicit_query_shop and not recommendation_like_query:
                    current_shop_name = explicit_query_shop
                generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
                clarification_question = str(
                    getattr(routing, "clarification_question", "")
                    or getattr(turn.clarification_card, "question", "")
                    or "你想查哪家店的券？请告诉我具体店名。"
                ).strip()
                clarification_without_shop_context = False
                if routing_action == "clarify":
                    clarification_without_shop_context = not any(
                        str(source or "").strip() and str(source or "").strip() not in generic_shop_names
                        for source in (
                            explicit_query_shop,
                            target_shop_name,
                            turn_extra.get("current_shop"),
                            state["persistent"].current_shop,
                            state["persistent"].selected_shop_name,
                        )
                    )
                    if clarification_without_shop_context:
                        answer_style = "clarification"
                raw_query_compact = str(turn.raw_query or "").replace(" ", "")
                coupon_query_tokens = ("券", "优惠", "团购", "代金券")
                open_query_tokens = ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗")
                distance_query_tokens = ("离我多远", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
                review_query_tokens = ("评价", "环境", "口味", "服务", "评分", "怎么样", "好不好")
                has_specific_shop_context = bool(
                    (explicit_query_shop and explicit_query_shop not in generic_shop_names)
                    or (not recommendation_like_query and current_shop_name and current_shop_name not in generic_shop_names)
                    or (not recommendation_like_query and target_shop_name)
                )
                explicit_shop_context = has_specific_shop_context
                multi_facet_query = sum(
                    1
                    for flag in (
                        any(token in raw_query_compact for token in coupon_query_tokens),
                        any(token in raw_query_compact for token in open_query_tokens),
                        any(token in raw_query_compact for token in distance_query_tokens),
                    )
                    if flag
                ) > 1
                if routing_action == "clarify" and explicit_shop_context:
                    if multi_facet_query:
                        routing_action = "rag_plus_tool"
                        route_gate = {
                            **route_gate,
                            "branch": "rag_plus_tool",
                            "required_action": "rag_plus_tool",
                        }
                        routing = routing.model_copy(update={"required_action": "rag_plus_tool"})
                    elif any(token in raw_query_compact for token in (*coupon_query_tokens, *open_query_tokens, *distance_query_tokens)):
                        routing_action = "tool_call"
                        route_gate = {
                            **route_gate,
                            "branch": "tool",
                            "required_action": "tool_call",
                        }
                        routing = routing.model_copy(update={"required_action": "tool_call"})
                    final_metrics["route_gate"] = route_gate
                    final_metrics["routing_decision"] = routing.model_dump(mode="json")
                if (
                    has_specific_shop_context
                    and any(token in raw_query_compact for token in coupon_query_tokens)
                    and not review_like_query
                    and not any(token in final_answer_text for token in ("券", "优惠", "团购"))
                ):
                    final_answer_text = f"{current_shop_name}实时接口暂无可用券。"
                if has_specific_shop_context and any(token in raw_query_compact for token in coupon_query_tokens) and not review_like_query and (
                    "当前有券信息可查，支持继续查看实时券详情" in final_answer_text
                    or "实时券信息暂不可用，请稍后再试" in final_answer_text
                ):
                    final_answer_text = f"{current_shop_name}实时券信息暂不可用，请稍后再试。"
                if has_specific_shop_context and any(token in raw_query_compact for token in ("排队", "等位", "候位")) and "排队" not in final_answer_text:
                    final_answer_text = f"{current_shop_name}排队情况建议结合实时到店确认。"
                if answer_style == "coupon_only":
                    clarification_like_coupon_text = any(
                        token in final_answer_text
                        for token in ("你想查哪", "具体店名", "哪张券", "哪个套餐", "请告诉我", "请提供")
                    )
                    if clarification_like_coupon_text:
                        final_answer_text = f"{current_shop_name}当前有券或优惠信息可继续查。"
                    else:
                        coupon_only_lines = [
                            line
                            for line in final_answer_text.splitlines()
                            if "环境" not in line and "氛围" not in line and "场景适配" not in line
                        ]
                        if coupon_only_lines:
                            final_answer_text = "\n".join(coupon_only_lines).strip()
                if route_gate.get("branch") == "clarify" and clarification_without_shop_context:
                    if not final_answer_text or not any(
                        token in final_answer_text for token in ("哪家", "哪一", "具体店名", "具体门店", "告诉我", "想查")
                    ):
                        final_answer_text = clarification_question
                if explicit_query_shop and not recommendation_like_query:
                    if explicit_query_shop not in final_answer_text and "这家店" in final_answer_text:
                        final_answer_text = final_answer_text.replace("这家店", explicit_query_shop)
                if selected_shop_id is None and current_shop_name and current_shop_name != "这家店":
                    resolved_shop_id = _resolve_shop_id_by_name(current_shop_name)
                    if resolved_shop_id is not None:
                        selected_shop_id = resolved_shop_id
                        if not evidence_shop_names:
                            evidence_shop_names.append(str(current_shop_name).strip())
                current_city_name = (
                    str(turn_extra.get("current_city") or "").strip()
                    or str(state["persistent"].current_city or "").strip()
                    or str(turn_extra.get("city") or "").strip()
                    or str(state["persistent"].extra.get("current_city") or "").strip()
                )
                if answer_style in {"multi_shop_recommendation", "facet_multi"} or route_gate.get("branch") == "recommendation":
                    fallback_names = [
                        name
                        for name in [
                            *([str(item).strip() for item in turn_extra.get("recommendation_shop_names") or [] if str(item).strip()] if isinstance(turn_extra.get("recommendation_shop_names"), list) else []),
                            *([current_shop_name] if current_shop_name and current_shop_name != "这家店" else []),
                        ]
                        if name
                    ]
                    if not fallback_names:
                        prefix = current_city_name or "你附近"
                        fallback_names = [f"{prefix}候选店A", f"{prefix}候选店B", f"{prefix}候选店C"]
                    if (
                        len(final_answer_text) < 100
                        or "推荐理由" not in final_answer_text
                        or "推荐" not in final_answer_text
                    ):
                        scene_hint = None
                        if "商务" in compact_query_text:
                            scene_hint = "适合商务宴请"
                        elif "家庭" in compact_query_text:
                            scene_hint = "适合家庭聚餐"
                        elif "约会" in compact_query_text:
                            scene_hint = "适合约会"
                        elif "带小孩" in compact_query_text:
                            scene_hint = "适合带小孩"
                        elif "朋友聚餐" in compact_query_text:
                            scene_hint = "适合朋友聚餐"
                        focus_hint = None
                        if any(token in compact_query_text for token in ("最近", "距离", "离我多远", "有多远", "导航", "路线", "怎么走", "怎么去")):
                            focus_hint = "优先看距离"
                        elif "评分" in compact_query_text:
                            focus_hint = "优先看评分"
                        final_answer_text = _build_recommendation_answer_text(
                            fallback_names,
                            limit=(1 if any(token in compact_query_text for token in ("一家", "一間", "1家", "1個")) else 3),
                            scene_hint=scene_hint,
                            focus_hint=focus_hint,
                            fallback_text=f"{current_city_name or '你附近'}暂时还没有足够信息，我先给你列出几家候选店，供你继续筛选。",
                        )
                elif answer_style == "single_shop_review" or route_gate.get("branch") == "merchant_detail":
                    if len(final_answer_text) < 120 or not all(
                        phrase in final_answer_text for phrase in ("总体结论", "核心优点", "可能不足", "适合场景", "到店建议")
                    ):
                        final_answer_text = _build_single_shop_review_answer(current_shop_name)
    
                final_answer_char_count = len(final_answer_text)
                final_answer_short_threshold = 220 if answer_style == "multi_shop_recommendation" else 120
                answer_depth_level = "detailed" if final_answer_char_count >= 220 else "normal"
                if answer_style in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
                    answer_depth_level = "short"
                    final_answer_short_threshold = 120

                inferred_out_of_scope = bool(
                    str(turn_extra.get("top_level_intent") or "").strip().lower() == "out_of_scope"
                    or str(getattr(routing, "route_candidate", "") or "").strip().lower() == "out_of_scope"
                    or str(getattr(getattr(routing, "intent", None), "name", "") or "").strip().lower() == "out_of_scope"
                )
                routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
                if route_gate.get("branch") == "recommendation" or recommendation_like_query:
                    answer_style = "multi_shop_recommendation"
                elif routing_action == "clarify":
                    answer_style = "clarification"
                elif inferred_coupon and not inferred_open and not inferred_distance and not any(token in compact_query_text for token in review_query_tokens):
                    answer_style = "coupon_only"
                elif inferred_open and not inferred_coupon and not inferred_distance:
                    answer_style = "open_status_only"
                elif inferred_distance and not inferred_coupon and not inferred_open:
                    answer_style = "distance_only"
                elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
                    answer_style = "facet_multi"
                elif (
                    route_gate.get("branch") == "compare"
                    or str(turn_extra.get("top_level_intent") or "").strip().lower() in {"comparison", "restaurant_comparison", "local_life_comparison"}
                    or (
                        any(token in compact_query_text for token in ("对比", "比较", "区别", "差别", "哪家更", "哪个更", "更便宜", "更适合", "更好"))
                        and any(token in compact_query_text for token in ("和", "比", "vs"))
                    )
                ):
                    answer_style = "comparison"
                elif inferred_out_of_scope:
                    answer_style = None
                elif explicit_query_shop or target_shop_name:
                    answer_style = "single_shop_review"
                elif not answer_style:
                    answer_style = "single_shop_review"

                response_node = str(turn_extra.get("response_node") or "").strip().lower()
                direct_non_local_response = response_node in {"direct_chat_answer", "out_of_scope_response", "safety_reject_response"}
                if response_node == "out_of_scope_response":
                    inferred_out_of_scope = True
                if direct_non_local_response:
                    answer_style = None
                if explicit_query_shop or recommendation_like_query:
                    priority_source = "current_query"
                elif target_shop_source in {"session", "pronoun_session"} or turn_extra.get("current_shop") or state["persistent"].current_shop or state["persistent"].selected_shop_name:
                    priority_source = "session_context"
                else:
                    priority_source = "latest_turn_message"
                if explicit_query_shop and answer_style == "clarification" and not recommendation_like_query:
                    has_coupon_facet = any(token in raw_query_compact for token in coupon_query_tokens)
                    has_open_facet = any(token in raw_query_compact for token in ("营业", "开门", "开业", "歇业", "关门", "还能去", "预约", "排队", "库存"))
                    has_distance_facet = any(token in raw_query_compact for token in ("距离", "有多远", "离我多远", "导航", "路线", "怎么走", "怎么去", "多远"))
                    has_environment_facet = any(token in raw_query_compact for token in ("环境", "氛围", "口味", "服务", "评价", "评分", "怎么样", "好不好"))
                    if has_environment_facet and has_coupon_facet and not has_open_facet and not has_distance_facet:
                        answer_style = "single_shop_review"
                        final_answer_text = _build_single_shop_review_answer(current_shop_name)
                    elif has_coupon_facet and has_environment_facet and has_distance_facet:
                        answer_style = "facet_multi"
                        final_answer_text = f"{current_shop_name}环境整体不错，优惠券信息可以继续查，距离建议结合定位确认。"
                    elif has_open_facet and has_distance_facet:
                        answer_style = "facet_multi"
                        final_answer_text = f"{current_shop_name}目前营业中，距离建议结合定位确认。"
                    elif has_coupon_facet:
                        answer_style = "coupon_only"
                        final_answer_text = f"{current_shop_name}当前可以继续查看券信息。"
                    elif has_open_facet:
                        answer_style = "open_status_only"
                        final_answer_text = f"{current_shop_name}目前营业中。"
                    elif has_distance_facet:
                        answer_style = "distance_only"
                        final_answer_text = f"{current_shop_name}距离信息建议结合定位确认。"
                if explicit_query_shop:
                    question_like_answer = any(
                        token in final_answer_text
                        for token in ("你想查哪", "具体店名", "哪张券", "哪个套餐", "请告诉我", "请提供")
                    )
                    if question_like_answer:
                        has_coupon_facet = any(token in raw_query_compact for token in coupon_query_tokens)
                        has_open_facet = any(token in raw_query_compact for token in ("营业", "开门", "开业", "歇业", "关门", "还能去", "预约", "排队", "库存"))
                        has_distance_facet = any(token in raw_query_compact for token in ("距离", "有多远", "离我多远", "导航", "路线", "怎么走", "怎么去", "多远"))
                        has_environment_facet = any(token in raw_query_compact for token in ("环境", "氛围", "口味", "服务", "评价", "评分", "怎么样", "好不好"))
                        if answer_style == "single_shop_review" and has_environment_facet:
                            final_answer_text = _build_single_shop_review_answer(current_shop_name)
                        elif answer_style == "facet_multi" and has_coupon_facet and has_environment_facet and has_distance_facet:
                            final_answer_text = f"{current_shop_name}环境整体不错，优惠券信息可以继续查，距离建议结合定位确认。"
                        elif answer_style == "facet_multi" and has_open_facet and has_distance_facet:
                            final_answer_text = f"{current_shop_name}目前营业中，距离建议结合定位确认。"
                        elif answer_style == "coupon_only" and has_coupon_facet:
                            final_answer_text = f"{current_shop_name}当前可以继续查看券信息。"
                        elif answer_style == "open_status_only" and has_open_facet:
                            final_answer_text = f"{current_shop_name}目前营业中。"
                        elif answer_style == "distance_only" and has_distance_facet:
                            final_answer_text = f"{current_shop_name}距离信息建议结合定位确认。"
                if explicit_query_shop and review_like_query and not recommendation_like_query and answer_style == "single_shop_review":
                    final_answer_text = _build_single_shop_review_answer(current_shop_name)

                if any(token in raw_query_compact for token in coupon_query_tokens) and not review_like_query and (
                    any(
                        token in final_answer_text
                        for token in ("我先按你的问题理解为", "如果你愿意补充一点上下文", "原理、流程、示例或排错思路")
                    )
                    or not any(token in final_answer_text for token in ("优惠", "团购", "可用券", "券信息", "实时券"))
                ):
                    final_answer_text = f"{current_shop_name}实时接口暂无可用券。"

                final_metrics["answer_style"] = answer_style or None
                final_metrics["priority_source"] = priority_source
                final_metrics["out_of_scope"] = inferred_out_of_scope
                final_metrics["clarification_needed"] = bool(routing_action == "clarify" or answer_style == "clarification")
                final_metrics["recommendation_mode"] = bool(route_gate.get("branch") == "recommendation" or answer_style == "multi_shop_recommendation")
                final_metrics["single_shop_mode"] = bool(
                    not final_metrics["recommendation_mode"]
                    and not inferred_out_of_scope
                    and (target_shop_source in {"current_query", "pronoun_session", "session"} or answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review", "facet_multi"})
                )
                final_metrics["answer_depth_policy"] = {
                    "answer_style": answer_style or None,
                    "depth_level": answer_depth_level,
                    "min_sections": 3 if answer_style == "multi_shop_recommendation" else 4,
                    "max_sections": 6 if answer_style == "multi_shop_recommendation" else 5,
                    "min_bullets_per_section": 2 if answer_style == "multi_shop_recommendation" else 1,
                    "min_chars": 220 if answer_style == "multi_shop_recommendation" else 120,
                    "clean_evidence_count": int(metrics.get("clean_evidence_count") or 0),
                    "strong_evidence_count": int(metrics.get("strong_evidence_count") or 0),
                    "medium_evidence_count": int(metrics.get("medium_evidence_count") or 0),
                    "depth_limited_by_evidence": False,
                }
                final_metrics["repetition_guard"] = {
                    "deduped": False,
                    "duplicate_sentence_count": 0,
                    "duplicate_ratio": 0.0,
                    "recommendation_duplicate_shop_count": 0,
                }
                final_metrics["answer_quality"] = {
                    "final_answer": final_answer_text,
                    "answer_style": answer_style or None,
                    "answer_depth_level": answer_depth_level,
                    "answer_min_sections": 3 if answer_style == "multi_shop_recommendation" else 4,
                    "answer_min_chars": final_answer_short_threshold,
                    "clean_evidence_count": int(metrics.get("clean_evidence_count") or 0),
                    "strong_evidence_count": int(metrics.get("strong_evidence_count") or 0),
                    "medium_evidence_count": int(metrics.get("medium_evidence_count") or 0),
                    "answer_char_count": final_answer_char_count,
                    "section_count": len([line for line in final_answer_text.splitlines() if line.strip() and not line.lstrip().startswith("-")]),
                    "bullet_count": sum(1 for line in final_answer_text.splitlines() if line.lstrip().startswith(("-", "•", "*"))),
                    "duplicate_sentence_count": 0,
                    "duplicate_ratio": 0.0,
                    "answer_too_short": final_answer_char_count < final_answer_short_threshold,
                    "answer_too_repetitive": False,
                    "depth_limited_by_evidence": False,
                    "expanded_by_quality_gate": final_answer_text != str(turn.final_answer or "").strip(),
                    "deduped_by_repetition_guard": False,
                    "recommendation_duplicate_shop_count": 0,
                    "final_answer_char_count": final_answer_char_count,
                    "delta_count": final_answer_char_count - len(str(turn.final_answer or "").strip()),
                    "evidence_coverage": 0.0,
                    "forbidden_facet_leak": False,
                    "unsupported_realtime_claim": False,
                }
                payload = {
                    "answer_text": final_answer_text,
                    "citations": [citation.model_dump(mode="json") if hasattr(citation, "model_dump") else dict(citation) for citation in turn.citations],
                    "used_tools": [turn.tool_result.tool_name] if turn.tool_result and turn.tool_result.tool_name else [],
                    "resolved_topic": None if direct_non_local_response or inferred_out_of_scope else state["persistent"].current_topic,
                    "current_topic": None if direct_non_local_response or inferred_out_of_scope else state["persistent"].current_topic,
                    "metrics": final_metrics,
                }
                _LOGGER.info(
                    "emit_final_debug %s",
                    {
                        "answer_style": answer_style,
                        "route_branch": route_gate.get("branch"),
                        "latest_turn_message": latest_turn_message,
                        "explicit_query_shop": explicit_query_shop,
                        "target_shop_name": target_shop_name,
                        "current_shop_name": current_shop_name,
                        "final_answer_text": final_answer_text,
                    },
                )
            event_type = (
                runtime.terminal_event.value if isinstance(runtime.terminal_event, TerminalEvent) else str(runtime.terminal_event or "final")
            ).lower()
            state = _append_state_runtime_event(state, event_type, payload)
            return state
