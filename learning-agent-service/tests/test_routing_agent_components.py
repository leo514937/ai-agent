from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from pydantic import BaseModel

from learning_agent_service.application.execution_plan_builder import (
    ExecutionPlanBuilder,
    ExecutionStep,
)
from learning_agent_service.application.main_chart import MainChart
from learning_agent_service.application.tool_chain_manager import ToolChainManager
from learning_agent_service.application.workflow_integration import WorkflowIntegration
from learning_agent_service.application.router_agent import RoutingAgent
from learning_agent_service.domain.contracts import FacetPlan
from learning_agent_service.local_life.hybrid_router import HybridRouter
from learning_agent_service.tools import SideEffectLevel, ToolExecutor, ToolRegistry, ToolSpec
from learning_agent_service.tools.tool_adapter import ToolAdapter
from learning_agent_service.tools.tool_call_validator import ToolCallValidator


class CouponToolInput(BaseModel):
    shop_id: int
    query: str


class CouponToolOutput(BaseModel):
    tool_name: str
    status: str
    output: dict


class ExecutionPlanBuilderTestCase(unittest.TestCase):
    def test_build_execution_plan_from_facets(self) -> None:
        builder = ExecutionPlanBuilder()
        resolved_shop = SimpleNamespace(id=1001, name="海底捞(水晶城店)")
        facet_plan = [
            FacetPlan(
                name="direct_answer",
                source="direct",
                execution_mode="direct",
            ),
            FacetPlan(
                name="coupon",
                source="tool",
                tool_name="get_coupon_list",
                execution_mode="single_shop_tool",
                required_target="single_shop",
            ),
        ]

        plan = builder.build_execution_plan(
            facet_plan=facet_plan,
            resolved_shop=resolved_shop,
            context={"query": "这家店有什么优惠券"},
        )

        self.assertEqual(plan.shop_id, 1001)
        self.assertEqual(len(plan.steps), 2)
        self.assertIsInstance(plan.steps[0], ExecutionStep)
        self.assertEqual(plan.steps[0].step_id, "direct_direct_answer")
        self.assertEqual(plan.steps[1].step_id, "execute_tool_get_coupon_list")
        self.assertEqual(plan.steps[1].params["shop_id"], 1001)
        self.assertGreater(plan.estimated_latency, 0)


class ToolChainManagerTestCase(unittest.TestCase):
    def _make_manager(self) -> ToolChainManager:
        registry = ToolRegistry()
        validator = ToolCallValidator(registry)
        adapter = ToolAdapter()
        executor = ToolExecutor(registry)
        manager = ToolChainManager(registry, validator, adapter, executor)
        manager.register_tool(
            tool_name="get_coupon_list",
            spec=ToolSpec(
                name="get_coupon_list",
                description="fetch coupons",
                input_model=CouponToolInput,
                output_model=CouponToolOutput,
                idempotent=True,
                retryable=False,
                side_effect_level=SideEffectLevel.NONE,
                requires_shop_id=True,
            ),
            handler=lambda payload: {
                "tool_name": "get_coupon_list",
                "status": "ok",
                "output": {
                    "shop_id": payload.shop_id,
                    "query": payload.query,
                },
            },
        )
        return manager

    def test_register_tool_and_lookup_spec(self) -> None:
        manager = self._make_manager()

        self.assertTrue(manager.is_tool_registered("get_coupon_list"))
        spec = manager.get_tool_spec("get_coupon_list")
        self.assertIsNotNone(spec)
        self.assertEqual(getattr(spec, "name", None), "get_coupon_list")

    def test_execute_tool_chain_success(self) -> None:
        manager = self._make_manager()

        result = asyncio.run(
            manager.execute_tool_chain(
                tool_name="get_coupon_list",
                input_payload={"shop_id": 1001, "query": "这家店有券吗"},
                resolved_shop=SimpleNamespace(id=1001, name="海底捞(水晶城店)"),
            )
        )

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.steps_completed, ["registry_validation", "tool_validation", "tool_adaptation", "tool_execution"])
        data = result.data or {}
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["output"]["output"]["shop_id"], 1001)

    def test_execute_tool_chain_rejects_unregistered_tool(self) -> None:
        manager = self._make_manager()

        result = asyncio.run(
            manager.execute_tool_chain(
                tool_name="unknown_tool",
                input_payload={"shop_id": 1001, "query": "x"},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.step, "registry_validation")
        self.assertIsNotNone(result.error)
        self.assertIn("not registered", result.error or "")


class MainChartTestCase(unittest.TestCase):
    def test_execute_returns_response_and_trace(self) -> None:
        chart = MainChart()

        result, trace = chart.execute("你好", context={"session_id": "session-1"})

        self.assertIsInstance(result, dict)
        self.assertEqual(result["response"], "这是一个示例响应。")
        self.assertEqual(result["metadata"]["tool_calls"], 0)
        self.assertEqual(trace["query"], "你好")
        self.assertIn("routing_result", trace)
        self.assertIn("response_result", trace)


class WorkflowIntegrationTestCase(unittest.TestCase):
    def test_integration_strategy_defaults_and_migration_state(self) -> None:
        registry = ToolRegistry()
        validator = ToolCallValidator(registry)
        adapter = ToolAdapter()
        executor = ToolExecutor(registry)
        tool_chain = ToolChainManager(registry, validator, adapter, executor)

        integration = WorkflowIntegration(
            new_routing_agent=RoutingAgent(llm=None),
            old_hybrid_router=HybridRouter(),
            new_tool_chain=tool_chain,
            legacy_components={"tool_executor": object(), "workflow_controller": object()},
        )

        self.assertEqual(integration.integration_strategy.routing_strategy, "hybrid")
        self.assertEqual(integration.integration_strategy.tool_chain_strategy, "parallel")
        self.assertEqual(integration.integration_strategy.workflow_strategy, "composition")
        self.assertEqual(integration.migration_state.transition_phase, "planning")


if __name__ == "__main__":
    unittest.main()
