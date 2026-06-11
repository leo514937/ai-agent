from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.application.router.stages.top_level_intent_router import (
    route_top_level_intent,
    TopLevelIntentResult,
)
from learning_agent_service.application.workflow.builder import _top_level_intent_route
from learning_agent_service.domain import (
    ChatTurnCommand,
    PersistentSessionContext,
    build_initial_state,
)


class TestTopLevelIntentRouter(unittest.TestCase):
    def test_capability_tokens(self):
        capability_queries = [
            "你有什么作用",
            "你有什么用",
            "你能做什么",
            "你可以做什么",
            "你会什么",
            "你能干嘛",
            "你能干什么",
            "你可以干嘛",
            "你可以干什么",
            "有什么功能",
            "有哪些功能",
            "你有什么功能",
            "你的功能",
            "有什么能力",
            "有哪些能力",
            "你有什么能力",
            "帮我做什么",
            "你可以帮我做什么",
            "这个助手有什么功能",
            "这个助手有什么作用",
        ]

        for query in capability_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "capability",
                f"Query '{query}' should be identified as capability, got {result.intent}",
            )
            self.assertIn("capability", result.matched_signals or [])

    def test_identity_tokens(self):
        identity_queries = [
            "你是谁",
            "你是什么",
            "你叫什么",
            "介绍一下你",
            "介绍你自己",
        ]

        for query in identity_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "identity",
                f"Query '{query}' should be identified as identity, got {result.intent}",
            )
            self.assertIn("identity", result.matched_signals or [])

    def test_help_tokens(self):
        help_queries = [
            "怎么用",
            "怎么用你",
            "怎么使用你",
            "如何使用",
            "使用说明",
        ]

        for query in help_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "help",
                f"Query '{query}' should be identified as help, got {result.intent}",
            )
            self.assertIn("help", result.matched_signals or [])

    def test_local_life_tokens(self):
        local_life_queries = [
            "海底捞怎么样",
            "海底捞有券吗",
            "附近有什么好吃的",
            "帮我推荐附近的火锅",
        ]

        for query in local_life_queries:
            result = route_top_level_intent(query)
            self.assertIn(
                result.intent,
                ["local_life", "recommendation"],
                f"Query '{query}' should be identified as local_life/recommendation, got {result.intent}",
            )

    def test_out_of_scope_tokens(self):
        out_of_scope_queries = [
            "帮我写代码",
            "写代码",
            "编程",
            "debug",
            "python",
            "sql",
        ]

        for query in out_of_scope_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "math_or_code",
                f"Query '{query}' should be identified as math_or_code, got {result.intent}",
            )

    def test_weak_meta_not_misidentify_domain_queries(self):
        domain_queries_should_not_be_capability = [
            ("海底捞有什么作用", "local_life"),
            ("海底捞有什么用", "local_life"),
            ("附近有什么功能比较全的商场", "recommendation"),
            ("这家店有什么功能", "local_life"),
            ("商场有什么功能", "local_life"),
            ("海底捞有什么用", "local_life"),
        ]

        for query, expected_intent in domain_queries_should_not_be_capability:
            result = route_top_level_intent(query)
            self.assertNotEqual(
                result.intent,
                "capability",
                f"Query '{query}' should NOT be capability, got {result.intent}",
            )
            self.assertIn(
                result.intent,
                ["local_life", "recommendation"],
                f"Query '{query}' should be {expected_intent}, got {result.intent}",
            )

    def test_comparison_tokens(self):
        comparison_queries = [
            "海底捞和巴奴哪个好",
            "海底捞和巴奴哪家好",
            "海底捞和巴奴哪个更好",
            "海底捞和巴奴哪家更好",
            "海底捞和巴奴对比一下",
            "海底捞和巴奴比一下",
            "海底捞比巴奴怎么样",
            "这两家哪个好",
            "这两个店哪个好",
        ]

        for query in comparison_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "comparison",
                f"Query '{query}' should be identified as comparison, got {result.intent}",
            )

    def test_address_business_hours_coupon_local_life(self):
        local_life_queries = [
            "海底捞地址在哪",
            "海底捞在哪",
            "营业时间是什么",
            "海底捞几点开门",
            "海底捞有券吗",
        ]

        for query in local_life_queries:
            result = route_top_level_intent(query)
            self.assertEqual(
                result.intent,
                "local_life",
                f"Query '{query}' should be identified as local_life, got {result.intent}",
            )

    def test_follow_up_requires_current_shop(self):
        ref_queries = [
            "这家地址在哪",
            "这家有券吗",
        ]

        for query in ref_queries:
            result = route_top_level_intent(query)
            self.assertTrue(
                result.requires_current_shop,
                f"Query '{query}' should require_current_shop=True, got {result.requires_current_shop}",
            )

    def test_context_pollution_protection(self):
        capability_queries = [
            "你有什么作用",
            "你有什么用",
            "怎么用你",
            "你是谁",
            "使用说明",
        ]

        for query in capability_queries:
            result = route_top_level_intent(query)
            self.assertIn(
                result.intent,
                ["capability", "identity", "help"],
                f"Query '{query}' with context should NOT become local_life, got {result.intent}",
            )


class TestTopLevelIntentRoute(unittest.TestCase):
    def _make_state(self, raw_query: str):
        command = ChatTurnCommand(
            trace_id="test_trace",
            session_id="test_session",
            turn_id="test_turn",
            user_id="test_user",
            message=raw_query,
        )
        persistent = PersistentSessionContext()
        return build_initial_state(
            command=command,
            workflow_version="test",
            persistent=persistent,
        )

    def _make_state_with_last_candidates(self, raw_query: str):
        command = ChatTurnCommand(
            trace_id="test_trace",
            session_id="test_session",
            turn_id="test_turn",
            user_id="test_user",
            message=raw_query,
        )
        persistent = PersistentSessionContext(
            last_candidates=[
                {"shop_id": 1, "name": "海底捞", "shop_name": "海底捞"},
                {"shop_id": 2, "name": "巴奴", "shop_name": "巴奴"},
            ]
        )
        return build_initial_state(
            command=command,
            workflow_version="test",
            persistent=persistent,
        )

    def _make_state_with_current_shop(self, raw_query: str):
        command = ChatTurnCommand(
            trace_id="test_trace",
            session_id="test_session",
            turn_id="test_turn",
            user_id="test_user",
            message=raw_query,
        )
        persistent = PersistentSessionContext(
            current_shop="海底捞",
            selected_shop_id=1,
        )
        state = build_initial_state(
            command=command,
            workflow_version="test",
            persistent=persistent,
        )
        turn_extra = dict(state["turn"].extra)
        turn_extra["current_shop"] = "海底捞"
        turn_extra["selected_shop_id"] = 1
        state["turn"] = state["turn"].model_copy(update={"extra": turn_extra})
        return state

    def test_capability_route(self):
        state = self._make_state("你有什么作用")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "capability_answer")

        turn_extra = state["turn"].extra
        self.assertIn("top_level_intent", turn_extra)
        intent_info = turn_extra["top_level_intent"]
        self.assertEqual(intent_info["intent"], "capability")

    def test_identity_route(self):
        state = self._make_state("你是谁")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "identity_answer")

    def test_help_route(self):
        state = self._make_state("怎么用你")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "capability_answer")

    def test_local_life_route(self):
        state = self._make_state("海底捞怎么样")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "resolve_target_shop")

    def test_unknown_input_route(self):
        state = self._make_state("随便输入一些内容")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "clarification_node")

    def test_requires_current_shop(self):
        state = self._make_state("这家怎么样")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "clarification_node")

        turn_extra = state["turn"].extra
        intent_info = turn_extra.get("top_level_intent", {})
        self.assertTrue(intent_info.get("requires_current_shop", False))

    def test_domain_query_not_capability(self):
        state = self._make_state("海底捞有什么作用")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "resolve_target_shop")

        turn_extra = state["turn"].extra
        intent_info = turn_extra.get("top_level_intent", {})
        self.assertNotEqual(intent_info.get("intent"), "capability")

    def test_comparison_route(self):
        state = self._make_state("海底捞和巴奴哪个好")
        route = _top_level_intent_route(state)
        self.assertEqual(route, "resolve_target_shop")

        turn_extra = state["turn"].extra
        intent_info = turn_extra.get("top_level_intent", {})
        self.assertEqual(intent_info.get("intent"), "comparison")

    def test_comparison_pronoun_no_candidates_goes_to_clarification(self):
        pronoun_queries = [
            "这两家哪个好",
            "这两个店哪个好",
            "它们哪个好",
            "这几个哪个好",
            "这些店哪个好",
        ]

        for query in pronoun_queries:
            state = self._make_state(query)
            route = _top_level_intent_route(state)
            self.assertEqual(
                route,
                "clarification_node",
                f"Query '{query}' without last_candidates should go to clarification_node, got {route}",
            )

            turn_extra = state["turn"].extra
            intent_info = turn_extra.get("top_level_intent", {})
            self.assertEqual(intent_info.get("intent"), "comparison")
            self.assertTrue(intent_info.get("requires_candidate_context", False))

    def test_comparison_pronoun_with_candidates_goes_to_resolve(self):
        pronoun_queries = [
            "这两家哪个好",
            "这两个店哪个好",
            "它们哪个好",
        ]

        for query in pronoun_queries:
            state = self._make_state_with_last_candidates(query)
            route = _top_level_intent_route(state)
            self.assertEqual(
                route,
                "resolve_target_shop",
                f"Query '{query}' with last_candidates should go to resolve_target_shop, got {route}",
            )

    def test_comparison_explicit_shops_always_resolve(self):
        explicit_queries = [
            "海底捞和巴奴哪个好",
            "海底捞和巴奴哪家好",
            "海底捞和巴奴哪个更好",
        ]

        for query in explicit_queries:
            state = self._make_state(query)
            route = _top_level_intent_route(state)
            self.assertEqual(
                route,
                "resolve_target_shop",
                f"Query '{query}' with explicit shops should go to resolve_target_shop, got {route}",
            )

            turn_extra = state["turn"].extra
            intent_info = turn_extra.get("top_level_intent", {})
            self.assertFalse(intent_info.get("requires_candidate_context", False))

    def test_bare_followup_no_current_shop_goes_to_clarification(self):
        bare_queries = [
            "地址在哪",
            "在哪",
            "有券吗",
            "营业时间是什么",
            "几点开门",
        ]

        for query in bare_queries:
            state = self._make_state(query)
            route = _top_level_intent_route(state)
            self.assertEqual(
                route,
                "clarification_node",
                f"Query '{query}' without current_shop should go to clarification_node, got {route}",
            )

            turn_extra = state["turn"].extra
            intent_info = turn_extra.get("top_level_intent", {})
            self.assertTrue(intent_info.get("requires_current_shop", False))

    def test_bare_followup_with_current_shop_goes_to_resolve(self):
        bare_queries = [
            "地址在哪",
            "在哪",
            "有券吗",
            "营业时间是什么",
            "几点开门",
        ]

        for query in bare_queries:
            state = self._make_state_with_current_shop(query)
            route = _top_level_intent_route(state)
            self.assertEqual(
                route,
                "resolve_target_shop",
                f"Query '{query}' with current_shop should go to resolve_target_shop, got {route}",
            )


if __name__ == "__main__":
    unittest.main()
