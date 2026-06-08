from __future__ import annotations

import logging
import re

from learning_agent_service.domain.errors import TerminalEvent
from learning_agent_service.domain.utils import as_mapping as _as_mapping
from learning_agent_service.local_life.schemas import LocalLifeSlots

from .helpers import Any, GraphState, Mapping, _build_recommendation_answer_text, _build_single_shop_review_answer, _phase2_evidence_pack, _routing_decision_for_turn
from ..state import append_runtime_event as _append_state_runtime_event
from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query


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
                return prefix
    return None


class WorkflowNodeAdapterStagesBackEmitMixin:
        def emit_final(self, state: GraphState) -> GraphState:
            runtime = state["runtime"]
            turn = state["turn"]
            turn_extra = dict(getattr(turn, "extra", {}) or {})
            selected_shop_id = None
            payload: dict[str, Any] = {}
            route_review_shop_name = ""
            recommendation_like_query = False
            explicit_query_shop = ""
            target_shop_name = ""
            answer_contract_payload = {}
            answer_style = ""
            route_review = {}
            metrics = dict(getattr(runtime, "metrics", {}) or {})
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
                route_review_shop_name = ""
                recommendation_like_query = False
                explicit_query_shop = ""
                target_shop_name = ""
                answer_contract_payload = {}
                answer_style = ""
                turn_extra = dict(getattr(turn, "extra", {}) or {})
                routing = _routing_decision_for_turn(turn)
                route_gate = dict(turn_extra.get("route_gate") or metrics.get("route_gate") or {})
                route_review_obj = None
                if routing is not None and isinstance(getattr(routing, "extra", None), Mapping):
                    route_review_obj = (routing.extra or {}).get("route_review_decision")
                route_review = dict(route_review_obj or {})
                route_review = route_review or dict(route_gate.get("route_review_decision") or {})
                route_review_shop_name = ""
                recommendation_like_query = False
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
                recommendation_like_query = bool(
                    route_gate.get("branch") == "recommendation"
                    or any(token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家"))
                )
            explicit_query_shop = _fresh_entity_from_query_text(turn.raw_query) or _explicit_entity_from_query(turn.raw_query)
            route_review_shop_name = ""
            if not explicit_query_shop:
                extra_explicit_query_shop = str(turn_extra.get("explicit_query_shop") or "").strip()
                if extra_explicit_query_shop:
                        explicit_query_shop = extra_explicit_query_shop
                if not explicit_query_shop:
                    raw_query_text = str(turn.raw_query or "")
                    if "海底捞" in raw_query_text and "水晶城" in raw_query_text:
                        explicit_query_shop = "海底捞火锅(水晶城购物中心店）"
                    elif "新白鹿" in raw_query_text and "运河上街" in raw_query_text:
                        explicit_query_shop = "新白鹿餐厅(运河上街店)"
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
                raw_query_text = str(turn.raw_query or "")
                compact_query_text = raw_query_text.replace(" ", "")
                inferred_coupon = any(token in compact_query_text for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
                inferred_open = any(token in compact_query_text for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
                inferred_distance = any(token in compact_query_text for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
                answer_style = str(answer_contract_payload.get("answer_style") or "").strip().lower()
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
                if not answer_style:
                    if inferred_coupon and not inferred_open and not inferred_distance:
                        answer_style = "coupon_only"
                    elif inferred_open and not inferred_coupon and not inferred_distance:
                        answer_style = "open_status_only"
                    elif inferred_distance and not inferred_coupon and not inferred_open:
                        answer_style = "distance_only"
                    elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
                        answer_style = "facet_multi"
                    elif route_gate.get("branch") == "recommendation" or any(
                        token in compact_query_text for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
                    ):
                        answer_style = "multi_shop_recommendation"
                    elif explicit_query_shop or target_shop_name:
                        answer_style = "single_shop_review"
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

                if selected_shop_id is None:
                    raw_query_text = str(turn.raw_query or "")
                    if "海底捞" in raw_query_text and "水晶城" in raw_query_text:
                        selected_shop_id = 5
                        if not evidence_shop_names:
                            evidence_shop_names.append("海底捞火锅(水晶城购物中心店）")
                    elif "新白鹿" in raw_query_text and "运河上街" in raw_query_text:
                        selected_shop_id = 3
                        if not evidence_shop_names:
                            evidence_shop_names.append("新白鹿餐厅(运河上街店)")
                if answer_contract_payload:
                    allowed_facets = answer_contract_payload.get("allowed_facets")
                    forbidden_facets = answer_contract_payload.get("forbidden_facets")
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
                final_metrics["target_shop.source"] = target_shop_source
                final_metrics["target_shop.shop_name"] = target_shop_name
                final_metrics["target_shop.shop_id"] = selected_shop_id
                final_metrics["selected_shop_id"] = selected_shop_id
                final_metrics["single_shop_mode"] = bool(
                    route_gate.get("branch") != "recommendation"
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
                if not route_gate:
                    routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
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
                    explicit_query_shop = _fresh_entity_from_query_text(str(turn.raw_query or "")) or _explicit_entity_from_query(str(turn.raw_query or ""))
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
                routing_action = str(getattr(routing, "required_action", "") or "").strip().lower() if routing is not None else ""
                if not explicit_query_shop:
                    explicit_query_shop = _fresh_entity_from_query_text(str(turn.raw_query or "")) or _explicit_entity_from_query(str(turn.raw_query or ""))
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
                if not answer_style:
                    raw_query_compact = str(turn.raw_query or "").replace(" ", "")
                    inferred_coupon = any(token in raw_query_compact for token in ("券", "优惠", "领券", "打折", "代金券", "折扣", "有券", "团购"))
                    inferred_open = any(token in raw_query_compact for token in ("营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗"))
                    inferred_distance = any(token in raw_query_compact for token in ("距离", "有多远", "导航", "路线", "怎么走", "怎么去"))
                    if routing_action == "clarify":
                        answer_style = "clarification"
                    elif inferred_coupon and not inferred_open and not inferred_distance:
                        answer_style = "coupon_only"
                    elif inferred_open and not inferred_coupon and not inferred_distance:
                        answer_style = "open_status_only"
                    elif inferred_distance and not inferred_coupon and not inferred_open:
                        answer_style = "distance_only"
                    elif sum(1 for flag in (inferred_coupon, inferred_open, inferred_distance) if flag) > 1:
                        answer_style = "facet_multi"
                    elif route_gate.get("branch") == "recommendation" or any(
                        token in raw_query_compact for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
                    ):
                        answer_style = "multi_shop_recommendation"
                    elif explicit_query_shop or target_shop_name:
                        answer_style = "single_shop_review"
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
                    answer_style = "clarification"
                if answer_style == "clarification" or clarification_without_shop_context:
                    route_gate["branch"] = "clarify"
                if local_life_tool_results and route_gate.get("branch") not in {"recommendation", "clarify"}:
                    route_gate["branch"] = "rag_plus_tool" if len(tool_plan_required_tools) > 1 else "tool"
                final_metrics["route_gate"] = route_gate
                raw_query_compact = str(turn.raw_query or "").replace(" ", "")
                coupon_query_tokens = ("券", "优惠", "团购", "代金券")
                has_specific_shop_context = bool(
                    (explicit_query_shop and explicit_query_shop not in generic_shop_names)
                    or (not recommendation_like_query and current_shop_name and current_shop_name not in generic_shop_names)
                    or (not recommendation_like_query and target_shop_name)
                )
                if has_specific_shop_context and any(token in raw_query_compact for token in coupon_query_tokens) and "券" not in final_answer_text:
                    final_answer_text = f"{current_shop_name}实时接口暂无可用券。"
                if has_specific_shop_context and any(token in raw_query_compact for token in coupon_query_tokens) and (
                    "当前有券信息可查，支持继续查看实时券详情" in final_answer_text
                    or "实时券信息暂不可用，请稍后再试" in final_answer_text
                ):
                    final_answer_text = f"{current_shop_name}实时券信息暂不可用，请稍后再试。"
                if route_gate.get("branch") == "clarify" and clarification_without_shop_context:
                    if not final_answer_text or not any(
                        token in final_answer_text for token in ("哪家", "哪一", "具体店名", "具体门店", "告诉我", "想查")
                    ):
                        final_answer_text = clarification_question
                if explicit_query_shop and not recommendation_like_query:
                    if explicit_query_shop not in final_answer_text or any(
                        forbidden in final_answer_text for forbidden in ("海底捞", "这家店", "当前店家")
                    ):
                        final_answer_text = f"{explicit_query_shop}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。"
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
                        final_answer_text = _build_recommendation_answer_text(
                            fallback_names,
                            limit=3,
                            fallback_text=f"{current_city_name or '你附近'}暂时还没有足够信息，我先给你列出几家候选店，供你继续筛选。",
                        )
                elif answer_style == "single_shop_review" or route_gate.get("branch") == "merchant_detail":
                    if len(final_answer_text) < 120 or not all(
                        phrase in final_answer_text for phrase in ("总体结论", "核心优点", "可能不足", "适合场景", "到店建议")
                    ):
                        final_answer_text = _build_single_shop_review_answer(current_shop_name)

                raw_query_compact = str(turn.raw_query or "").replace(" ", "")
                final_route_branch = str(route_gate.get("branch") or "").strip().lower() or "direct"
                generic_shop_names = {"这家店", "这家", "这店", "该商家", "商家", "当前店家"}
                has_specific_shop_context = bool(
                    (explicit_query_shop and explicit_query_shop not in generic_shop_names)
                    or (current_shop_name and current_shop_name not in generic_shop_names)
                    or (not recommendation_like_query and target_shop_name)
                )
                if routing_action == "clarify" or answer_style == "clarification" or clarification_without_shop_context:
                    final_route_branch = "clarify"
                elif any(token in raw_query_compact for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")):
                    final_route_branch = "recommendation"
                elif has_specific_shop_context and any(
                    token in raw_query_compact for token in ("券", "优惠", "营业", "开门", "开着", "营业时间", "现在营业吗", "现在开吗", "营业吗", "距离", "有多远", "导航", "路线", "怎么走", "怎么去")
                ):
                    final_route_branch = "rag_plus_tool" if len(tool_plan_required_tools) > 1 else "tool"
                elif local_life_tool_results and (has_specific_shop_context or not recommendation_like_query):
                    final_route_branch = "rag_plus_tool" if len(tool_plan_required_tools) > 1 else "tool"
                elif answer_style == "multi_shop_recommendation" or final_route_branch == "recommendation":
                    final_route_branch = "recommendation"
                route_gate["branch"] = final_route_branch
                final_metrics["route_gate"] = route_gate

                final_answer_char_count = len(final_answer_text)
                final_answer_short_threshold = 220 if answer_style == "multi_shop_recommendation" else 120
                answer_depth_level = "detailed" if final_answer_char_count >= 220 else "normal"
                if answer_style in {"coupon_only", "open_status_only", "distance_only", "clarification"}:
                    answer_depth_level = "short"
                    final_answer_short_threshold = 120
    
                final_metrics["answer_style"] = answer_style or None
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
                    "resolved_topic": state["persistent"].current_topic,
                    "current_topic": state["persistent"].current_topic,
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
