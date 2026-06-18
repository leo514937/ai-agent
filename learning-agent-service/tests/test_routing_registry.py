from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.routing_registry import (
    get_route_entry,
    resolve_execution_route,
    resolve_top_level_route,
)


class TestRoutingRegistry(unittest.TestCase):
    def test_top_level_route_for_comparison_maps_to_local_life(self) -> None:
        match = resolve_top_level_route("comparison")

        self.assertTrue(match["supported"])
        self.assertEqual(match["route_id"], "local_life")
        self.assertEqual(match["entry_node"], "query_merge_for_local_life")

    def test_execution_route_for_tool_call_prefers_tool(self) -> None:
        match = resolve_execution_route(required_action="tool_call", route_candidate="merchant_status_tool")

        self.assertTrue(match["supported"])
        self.assertEqual(match["route_id"], "tool")
        self.assertEqual(match["entry_node"], "tool_subgraph")

    def test_execution_route_for_recommendation_prefers_recommendation(self) -> None:
        match = resolve_execution_route(required_action="recommendation", route_candidate="local_life.combo")

        self.assertTrue(match["supported"])
        self.assertEqual(match["route_id"], "recommendation")
        self.assertEqual(match["entry_node"], "recommendation_subgraph")

    def test_rag_route_is_not_registered(self) -> None:
        self.assertIsNone(get_route_entry("rag"))

    def test_unknown_execution_route_falls_back_to_direct_or_clarify(self) -> None:
        match = resolve_execution_route(required_action="mystery_action", route_candidate="mystery_route")

        self.assertFalse(match["supported"])
        self.assertIn(match["route_id"], {"direct", "clarify"})


if __name__ == "__main__":
    unittest.main()
