"""
RoutingPolicyValidator — 规则层最终决策。

RoutingAgent 只建议"走哪条路"，Validator 决定是否放行：
- 决定是否进入 Tool 路径
- 确保 shop_id 已绑定（单店工具必须有 resolved_shop_id）
- 修正 LLM 路由决策中的错误
- clarify/jailbreak 直接输出响应，不进入子图执行层
"""

from __future__ import annotations

from typing import Any

from learning_agent_service.domain.contracts import FacetPlan, RoutingDecision, SemanticParseResult
from learning_agent_service.domain.enums import (
    LocalRouteType,
    NegativeScopeType,
    PolarityType,
    TargetType,
)
from learning_agent_service.application.routing_registry import (
    resolve_execution_route,
    resolve_top_level_route,
    route_registry_hits,
)


class RoutingPolicyValidator:
    """规则层校验 — 拥有最终执行权。

    职责：
    1. 决定是否进入 Tool 路径
    2. 确保 shop_id 已绑定（单店工具必须有 resolved_shop_id）
    3. 修正 LLM 路由决策中的明显错误
    4. 根据 FacetPlan.required_target 决定是否需要 tool chain
    """

    def validate(
        self,
        routing: RoutingDecision,
        resolved_shop: Any = None,
    ) -> RoutingDecision:
        """校验路由决策，决定是否执行。

        Args:
            routing: RoutingAgent 输出的路由决策
            resolved_shop: BusinessObjectResolver 解析结果（可选）

        Returns:
            校验后的 RoutingDecision
        """
        routing = self._attach_registry_metadata(routing)
        routing = self._ensure_semantic_frame(routing)
        execution_match = self._execution_match(routing)
        canonical_route = str(execution_match.get("route_id") or "").strip().lower() or None
        semantic_route = str(getattr(getattr(routing, "semantic_parse_result", None), "local_route", "") or "").strip().lower()
        if semantic_route in {"recommendation", "comparison"}:
            canonical_route = "recommendation"
        elif semantic_route in {"single_shop", "realtime_tool", "merchant_reasoning", "transaction"}:
            canonical_route = "tool"
        elif semantic_route == "clarify":
            canonical_route = "clarify"
        elif semantic_route == "local_chat":
            canonical_route = "direct"
        routing = routing.model_copy(update={
            "canonical_route": canonical_route,
            "required_sources": self._resolve_required_sources(routing),
        })

        # 1. Early exit: clarify / jailbreak 直接放行
        if routing.capability_line in ("clarify", "jailbreak"):
            return self._attach_routing_trace(
                routing,
                validator_decision=routing.capability_line,
                execution_match=execution_match,
            )

        # 2. 检查是否为 direct（不需要 tool 链）
        if routing.capability_line == "direct":
            return self._attach_routing_trace(
                self._validate_direct(routing),
                validator_decision="validated",
                execution_match=execution_match,
            )

        if not execution_match.get("supported", False):
            if (
                routing.required_action in {"tool_call", "recommendation"}
                and bool(routing.should_call_tool)
                and str(getattr(routing, "capability_line", "") or "").strip().lower().endswith("_tool")
            ):
                pass
            else:
                routing = self._apply_registry_fallback(routing, execution_match)
                if routing.capability_line in ("clarify", "jailbreak"):
                    return self._attach_routing_trace(
                        routing,
                        validator_decision="registry_fallback",
                        execution_match=execution_match,
                    )
                if routing.capability_line == "direct":
                    return self._attach_routing_trace(
                        self._validate_direct(routing),
                        validator_decision="registry_fallback",
                        execution_match=execution_match,
                    )

        # 3. 校验 FacetPlan 一致性
        routing = self._validate_facet_plan(routing, resolved_shop)

        # 4. 检查是否可以执行 ToolCall
        routing = self._can_execute_tools(routing, resolved_shop)

        return self._attach_routing_trace(
            routing,
            validator_decision="validated",
            execution_match=execution_match,
        )

    def _attach_registry_metadata(self, routing: RoutingDecision) -> RoutingDecision:
        """把注册表判定写回 extra，供后续路由门和 trace 使用。"""
        routing_extra = dict(getattr(routing, "extra", {}) or {})
        top_level_payload = routing_extra.get("top_level_intent")
        if not isinstance(top_level_payload, dict):
            top_level_payload = {}
        top_level_intent = str(
            top_level_payload.get("intent")
            or getattr(getattr(routing, "intent", None), "name", "")
            or ""
        ).strip().lower()
        route_candidate = str(
            routing_extra.get("unsupported_route_candidate")
            or routing_extra.get("proposed_route_candidate")
            or routing_extra.get("original_route_candidate")
            or routing_extra.get("resolved_route_candidate")
            or routing.route_candidate
            or routing_extra.get("route_candidate")
            or ""
        ).strip().lower() or None
        route_candidates = routing_extra.get("route_candidates")
        if not isinstance(route_candidates, list):
            route_candidates = []
        execution_match = resolve_execution_route(
            required_action=routing.required_action,
            route_candidate=route_candidate,
            top_level_intent=top_level_intent,
            route_candidates=route_candidates,
        )
        top_level_match = resolve_top_level_route(
            top_level_intent,
            route_candidate=route_candidate,
            route_candidates=route_candidates,
        )
        registry_hits = route_registry_hits(
            {
                "route_candidate": route_candidate,
                "top_level_intent": top_level_intent,
                "required_action": routing.required_action,
            },
            route_candidates,
        )
        if route_candidate and not any(str(hit.get("matched_value") or "").strip().lower() == route_candidate for hit in registry_hits):
            routing_extra["unsupported_route_candidate"] = route_candidate
        routing_extra["route_registry_hits"] = registry_hits
        routing_extra["resolved_route_candidate"] = str(execution_match.get("route_id") or "").strip().lower() or None
        routing_extra["resolved_top_level_route"] = str(top_level_match.get("route_id") or "").strip().lower() or None
        if top_level_payload:
            routing_extra["top_level_intent"] = {
                **top_level_payload,
                "resolved_route_candidate": routing_extra["resolved_top_level_route"],
            }
        return routing.model_copy(update={"extra": routing_extra})

    def _attach_routing_trace(
        self,
        routing: RoutingDecision,
        *,
        validator_decision: str,
        execution_match: dict[str, Any],
    ) -> RoutingDecision:
        routing_extra = dict(getattr(routing, "extra", {}) or {})
        routing_trace = dict(routing_extra.get("routing_trace") or {})
        route_id = str(execution_match.get("route_id") or routing.canonical_route or "").strip().lower()
        basis_parts = [
            part
            for part in (
                "canonical_route" if route_id else "",
                "required_action" if str(getattr(routing, "required_action", "") or "").strip() else "",
                "facet_plan" if list(getattr(routing, "facet_plan", []) or []) else "",
                "required_sources" if list(getattr(routing, "required_sources", []) or []) else "",
            )
            if part
        ]
        routing_trace.update(
            {
                "global_intent_source": routing_trace.get("global_intent_source") or self._trace_source_from_routing(routing),
                "semantic_frame_source": routing_trace.get("semantic_frame_source") or self._trace_source_from_routing(routing),
                "validator_decision": validator_decision,
                "fallback_used": bool(routing_trace.get("fallback_used", False)),
                "legacy_router_used": bool(routing_trace.get("legacy_router_used", False)),
                "final_dispatch_basis": "+".join(basis_parts) if basis_parts else "legacy_fallback",
                "canonical_route": route_id or routing.canonical_route,
                "required_action": routing.required_action,
                "required_sources": list(getattr(routing, "required_sources", []) or []),
            }
        )
        routing_extra["routing_trace"] = routing_trace
        return routing.model_copy(update={"extra": routing_extra})

    def _trace_source_from_routing(self, routing: RoutingDecision) -> str:
        semantic_frame = getattr(routing, "semantic_parse_result", None)
        if semantic_frame is not None:
            return "router_agent"
        return "registry_fallback"

    def _ensure_semantic_frame(self, routing: RoutingDecision) -> RoutingDecision:
        semantic_frame = getattr(routing, "semantic_parse_result", None)
        if semantic_frame is None:
            semantic_frame = SemanticParseResult(
                primary_intent=str(getattr(routing, "route_candidate", "") or routing.required_action or "query"),
                top_level_intent=str(getattr(getattr(routing, "intent", None), "name", "") or "local_life"),
                sub_intents=[],
                polarity=PolarityType.NEUTRAL,
                negative_scope=NegativeScopeType.ACTION,
                target_type=TargetType.AMBIGUOUS,
                local_route=self._local_route_from_capability(routing.capability_line),
                required_facets=[facet.name for facet in list(getattr(routing, "facet_plan", []) or []) if str(getattr(facet, "name", "") or "").strip()],
                required_sources=self._resolve_required_sources(routing),
                needs_context=False,
                confidence=float(getattr(routing, "confidence", 0.0) or 0.0),
                extra={"source": "validator_default"},
            )
        routing = routing.model_copy(update={
            "semantic_parse_result": semantic_frame,
        })
        if not list(getattr(routing, "required_sources", []) or []):
            routing = routing.model_copy(update={
                "required_sources": self._resolve_required_sources(routing),
            })
        return routing

    def _local_route_from_capability(self, capability_line: str) -> LocalRouteType:
        normalized = str(capability_line or "").strip().lower()
        if normalized == "recommendation_tool":
            return LocalRouteType.RECOMMENDATION
        if normalized == "comparison_tool":
            return LocalRouteType.COMPARISON
        if normalized == "transaction_tool":
            return LocalRouteType.TRANSACTION
        if normalized == "clarify":
            return LocalRouteType.CLARIFY
        if normalized == "jailbreak":
            return LocalRouteType.CLARIFY
        if normalized == "single_shop_tool":
            return LocalRouteType.SINGLE_SHOP
        return LocalRouteType.LOCAL_CHAT

    def _resolve_required_sources(self, routing: RoutingDecision) -> list[str]:
        semantic_frame = getattr(routing, "semantic_parse_result", None)
        if semantic_frame is not None and list(getattr(semantic_frame, "required_sources", []) or []):
            return list(dict.fromkeys(str(item).strip() for item in semantic_frame.required_sources if str(item).strip()))

        sources: list[str] = []
        for facet in list(getattr(routing, "facet_plan", []) or []):
            source = str(getattr(facet, "source", "") or "").strip()
            if source:
                sources.append(source)
        if not sources and str(getattr(routing, "capability_line", "") or "").strip().lower() == "recommendation_tool":
            sources.append("recommendation")
        return list(dict.fromkeys(sources))

    def _execution_match(self, routing: RoutingDecision) -> dict[str, Any]:
        routing_extra = dict(getattr(routing, "extra", {}) or {})
        top_level_payload = routing_extra.get("top_level_intent")
        if not isinstance(top_level_payload, dict):
            top_level_payload = {}
        top_level_intent = str(
            top_level_payload.get("intent")
            or getattr(getattr(routing, "intent", None), "name", "")
            or ""
        ).strip().lower()
        route_candidate = str(
            routing_extra.get("unsupported_route_candidate")
            or routing_extra.get("proposed_route_candidate")
            or routing_extra.get("original_route_candidate")
            or routing_extra.get("resolved_route_candidate")
            or routing.route_candidate
            or routing_extra.get("route_candidate")
            or ""
        ).strip().lower() or None
        route_candidates = routing_extra.get("route_candidates")
        if not isinstance(route_candidates, list):
            route_candidates = []
        return resolve_execution_route(
            required_action=routing.required_action,
            route_candidate=route_candidate,
            top_level_intent=top_level_intent,
            route_candidates=route_candidates,
        )

    def _apply_registry_fallback(self, routing: RoutingDecision, execution_match: dict[str, Any]) -> RoutingDecision:
        fallback_route = str(execution_match.get("route_id") or "").strip().lower()
        if fallback_route == "clarify":
            return routing.model_copy(update={
                "capability_line": "clarify",
                "required_action": "clarify",
                "should_call_tool": False,
                "should_retrieve": False,
            })
        if fallback_route == "direct":
            return self._validate_direct(routing)
        return routing

    def _validate_direct(self, routing: RoutingDecision) -> RoutingDecision:
        """校验 direct 线路。"""
        # 确保 direct 不应该 call tool
        updates: dict[str, Any] = {"capability_line": "direct", "should_call_tool": False}
        if str(getattr(routing, "required_action", "") or "").strip().lower() not in {"direct_answer", "memory_update", "no_op", "reject"}:
            updates["required_action"] = "direct_answer"
        return routing.model_copy(update=updates)

    def _can_execute_tools(
        self,
        routing: RoutingDecision,
        resolved_shop: Any = None,
    ) -> RoutingDecision:
        """检查是否可以执行 ToolCall。"""
        # 如果没有 facet_plan 就不需要走 tool
        if not routing.facet_plan:
            if routing.required_action in {"tool_call", "recommendation"} or routing.capability_line in {
                "single_shop_tool",
                "recommendation_tool",
                "comparison_tool",
                "transaction_tool",
            }:
                return routing
            if routing.capability_line == "single_shop_tool" and resolved_shop is None:
                return self._handle_missing_shop_id(
                    routing,
                    FacetPlan(name="shop_info", source="tool", execution_mode="single_shop_tool", required_target="single_shop"),
                    question="请问您想了解哪家店？",
                )
            return routing.model_copy(update={"should_call_tool": False})

        # 检查每个 single_shop facet 是否有 resolved_shop_id
        for facet in routing.facet_plan:
            if facet.source == "tool" and facet.required_target == "single_shop":
                if resolved_shop is None:
                    # 没有 resolved_shop → 改为 clarify
                    return self._handle_missing_shop_id(
                        routing,
                        facet,
                        question="请问您想了解哪家店？",
                    )
                # 有 resolved_shop 但 id 为空
                shop_id = getattr(resolved_shop, "id", None)
                if shop_id is None:
                    return self._handle_missing_shop_id(
                        routing,
                        facet,
                        question="请问您想了解哪家店？",
                    )

        # 所有检查通过
        return routing

    def _handle_missing_shop_id(
        self,
        routing: RoutingDecision,
        facet: FacetPlan,
        question: str = "请问您想了解哪家店？",
    ) -> RoutingDecision:
        """处理缺失 shop_id 的情况。

        推荐类 facet 可以继续，其他 single_shop facet 需要澄清。
        """
        if facet.name == "recommendation":
            return routing

        if facet.ambiguity_policy == "candidate_list":
            return routing

        if facet.ambiguity_policy == "skip":
            return routing

        return routing.model_copy(update={
            "capability_line": "clarify",
            "required_action": "clarify",
            "clarification_question": question,
            "missing_slots": [*routing.missing_slots, "shop_id"],
            "should_call_tool": False,
        })

    def _validate_facet_plan(
        self,
        routing: RoutingDecision,
        resolved_shop: Any = None,
    ) -> RoutingDecision:
        """校验 FacetPlan 一致性。"""
        shop_id: int | None = None
        if resolved_shop is not None:
            shop_id = getattr(resolved_shop, "id", None)

        updated_facets: list[FacetPlan] = []
        need_shop_check = False

        for facet in routing.facet_plan:
            # 注入 shop_id 到 single_shop facet
            if facet.required_target == "single_shop" and shop_id is not None:
                facet.extra["shop_id"] = shop_id
                need_shop_check = True

            # 设置 execution_mode
            if not facet.execution_mode or facet.execution_mode == "direct":
                facet = facet.model_copy(update={
                    "execution_mode": routing.capability_line,
                })

            updated_facets.append(facet)

        result = routing.model_copy(update={"facet_plan": updated_facets})

        # 如果有 single_shop facet 但 resolved_shop_id 未设置，尝试设置
        if need_shop_check and result.resolved_shop_id is None and shop_id is not None:
            result = result.model_copy(update={"resolved_shop_id": shop_id})

        return result
