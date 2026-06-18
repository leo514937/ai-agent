from __future__ import annotations

from types import SimpleNamespace
import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router_agent import RoutingAgent
from learning_agent_service.application.routing_policy_validator import RoutingPolicyValidator
from learning_agent_service.application.workflow.adapters.helpers import build_routing_trace_from_state
from learning_agent_service.domain.contracts import FacetPlan, RoutingDecision, SemanticParseResult
from learning_agent_service.domain.enums import (
    LocalRouteType,
    NegativeScopeType,
    PolarityType,
    TargetType,
)


class RoutingSemanticFrameTestCase(unittest.TestCase):
    def test_semantic_frame_enums_are_stable(self) -> None:
        self.assertEqual(PolarityType.NEGATIVE_QUESTION.value, "negative_question")
        self.assertEqual(NegativeScopeType.SHOP.value, "shop")
        self.assertEqual(TargetType.SHOP.value, "shop")
        self.assertEqual(LocalRouteType.SINGLE_SHOP.value, "single_shop")

    def test_routing_agent_populates_semantic_frame_for_negative_shop_question(self) -> None:
        agent = RoutingAgent(llm=None)

        decision, trace = agent.route("不推荐海底捞")

        self.assertIsNotNone(decision.semantic_parse_result)
        frame = decision.semantic_parse_result
        self.assertEqual(frame.polarity, PolarityType.NEGATIVE_QUESTION)
        self.assertEqual(frame.negative_scope, NegativeScopeType.SHOP)
        self.assertEqual(frame.target_type, TargetType.SHOP)
        self.assertIn(frame.local_route, {LocalRouteType.SINGLE_SHOP, LocalRouteType.MERCHANT_REASONING})
        self.assertEqual(trace.global_intent_source, "keyword_fallback")
        self.assertEqual(trace.semantic_frame_source, "keyword_fallback")
        self.assertFalse(trace.legacy_router_used)

    def test_validator_sets_canonical_route_and_required_sources(self) -> None:
        decision = RoutingDecision(
            raw_query="附近有什么火锅店推荐",
            domain="local_life",
            capability_line="recommendation_tool",
            required_action="tool_call",
            should_call_tool=True,
            route_candidate="recommendation_tool",
            confidence=0.91,
            semantic_parse_result=SemanticParseResult(
                primary_intent="recommendation",
                top_level_intent="local_life",
                sub_intents=["recommendation"],
                required_facets=["recommendation"],
                optional_facets=["distance_eta"],
                forbidden_facets=[],
                polarity=PolarityType.POSITIVE,
                negative_scope=NegativeScopeType.ACTION,
                target_type=TargetType.CATEGORY,
                target_categories=["火锅"],
                excluded_shops=[],
                excluded_categories=[],
                excluded_features=[],
                constraints={},
                facets=["recommendation"],
                required_sources=["recommendation"],
                needs_context=False,
                local_route=LocalRouteType.RECOMMENDATION,
                confidence=0.91,
                missing_slots=[],
            ),
            facet_plan=[
                FacetPlan(
                    name="recommendation",
                    source="recommendation",
                    execution_mode="recommendation_tool",
                )
            ],
        )

        validator = RoutingPolicyValidator()
        validated = validator.validate(decision)

        self.assertEqual(validated.canonical_route, "recommendation")
        self.assertIsNotNone(validated.semantic_parse_result)
        self.assertEqual(validated.semantic_parse_result.local_route, LocalRouteType.RECOMMENDATION)
        self.assertEqual(validated.required_sources, ["recommendation"])
        self.assertIsNotNone(validated.extra.get("routing_trace"))
        self.assertEqual(validated.extra["routing_trace"]["validator_decision"], "validated")

    def test_build_routing_trace_from_state_surfaces_routing_trace_metadata(self) -> None:
        state = SimpleNamespace(
            turn=SimpleNamespace(
                extra={
                    "routing_trace": {
                        "global_intent_source": "router_agent",
                        "semantic_frame_source": "router_agent",
                        "validator_decision": "validated",
                        "fallback_used": False,
                        "legacy_router_used": False,
                        "final_dispatch_basis": "canonical_route",
                    }
                },
                routing_decision=SimpleNamespace(
                    extra={
                        "routing_trace": {
                            "canonical_route": "recommendation",
                            "required_action": "tool_call",
                        }
                    }
                ),
            ),
            runtime=SimpleNamespace(metrics={}),
        )

        trace = build_routing_trace_from_state(state)

        self.assertEqual(trace["global_intent_source"], "router_agent")
        self.assertEqual(trace["semantic_frame_source"], "router_agent")
        self.assertEqual(trace["validator_decision"], "validated")
        self.assertFalse(trace["fallback_used"])
        self.assertFalse(trace["legacy_router_used"])
        self.assertEqual(trace["final_dispatch_basis"], "canonical_route")
        self.assertEqual(trace["canonical_route"], "recommendation")


if __name__ == "__main__":
    unittest.main()
