"""端到端路由收口验证测试

从 /internal/v1/chat/stream 接口出发，覆盖所有路由分支：
  1. direct         — 闲聊 / 超出范围
  2. single_shop    — 单店查询（怎么样/好不好）
  3. recommendation — 推荐（推荐几家/附近好吃的）
  4. comparison     — 对比（海底捞和巴奴哪个更适合约会）
  5. tool_coupon    — 单店工具：优惠券
  6. tool_open      — 单店工具：营业状态
  7. tool_distance  — 单店工具：距离
  8. clarify        — 追问（没有明确店名的代词引用）
  9. jailbreak/oos  — 超范围拦截（天气/音乐等）
 10. facet_multi    — 多维度混合查询

每个 case 独立 session_id，自包含，不依赖外部服务运行。
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 路径设置
TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient, ChatStreamResult


# ---------------------------------------------------------------------------
# 辅助结构
# ---------------------------------------------------------------------------
@dataclass
class E2ECase:
    case_id: str
    description: str
    message: str
    session_id: str
    extra_payload: dict[str, Any] | None = None
    # 断言：期望 metrics 中的 answer_style
    expect_answer_style: str | list[str] | None = None
    # 断言：final_answer 包含的关键词
    expect_answer_contains: list[str] = field(default_factory=list)
    # 断言：final_answer 不包含的关键词
    expect_answer_not_contains: list[str] = field(default_factory=list)
    # 断言：期望 metrics 中的特定字段值
    expect_metrics: dict[str, Any] = field(default_factory=dict)
    # 前置消息（用于多轮会话）
    pre_messages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 测试用例定义
# ---------------------------------------------------------------------------
E2E_CASES: list[E2ECase] = [
    # ── 1. 闲聊 / 超范围 ──
    E2ECase(
        case_id="E2E-01-direct-greeting",
        description="普通问候应被识别为 out_of_scope，返回引导语",
        message="你好",
        session_id="e2e-direct-greeting",
        expect_answer_contains=["帮你", "商家"],
        expect_metrics={"out_of_scope": True},
    ),

    # ── 2. 超出领域拦截（jailbreak / oos）──
    E2ECase(
        case_id="E2E-02-oos-weather",
        description="天气类问题应被识别为超出本地生活范围",
        message="今天北京天气怎么样",
        session_id="e2e-oos-weather",
        expect_answer_contains=["超出"],
        expect_metrics={"out_of_scope": True},
    ),
    E2ECase(
        case_id="E2E-03-oos-music",
        description="音乐类问题应被拦截",
        message="推荐一首好听的歌曲",
        session_id="e2e-oos-music",
        expect_answer_contains=["超出"],
        expect_metrics={"out_of_scope": True},
    ),

    # ── 3. 单店查询 ──
    E2ECase(
        case_id="E2E-04-single-shop-review",
        description="带明确店名的单店评价查询",
        message="海底捞怎么样",
        session_id="e2e-single-shop-review",
        expect_answer_style=["single_shop_review", "facet_multi"],
        expect_answer_contains=["海底捞"],
        expect_metrics={"single_shop_mode": True},
    ),
    E2ECase(
        case_id="E2E-05-single-shop-taste",
        description="带明确店名的口味维度查询",
        message="海底捞口味怎么样",
        session_id="e2e-single-shop-taste",
        expect_answer_style=["single_shop_review", "facet_multi"],
        expect_answer_contains=["口味"],
        expect_metrics={"single_shop_mode": True},
    ),

    # ── 4. 推荐 ──
    E2ECase(
        case_id="E2E-06-recommendation-basic",
        description="推荐类查询应走推荐路径",
        message="上海有什么好吃的火锅推荐",
        session_id="e2e-recommend-basic",
        expect_answer_style="multi_shop_recommendation",
        expect_answer_contains=["推荐"],
        expect_metrics={"recommendation_mode": True, "single_shop_mode": False},
    ),
    E2ECase(
        case_id="E2E-07-recommendation-scene",
        description="场景化推荐：约会场景",
        message="推荐一家适合约会的餐厅",
        session_id="e2e-recommend-scene",
        expect_answer_style="multi_shop_recommendation",
        expect_answer_contains=["推荐", "约会"],
        expect_metrics={"recommendation_mode": True},
    ),
    E2ECase(
        case_id="E2E-08-recommendation-nearby",
        description="附近推荐",
        message="附近有什么好吃的餐厅推荐",
        session_id="e2e-recommend-nearby",
        expect_answer_style="multi_shop_recommendation",
        expect_answer_contains=["推荐"],
        expect_metrics={"recommendation_mode": True},
    ),

    # ── 5. 对比 ──
    E2ECase(
        case_id="E2E-09-comparison",
        description="两家店对比查询",
        message="海底捞和巴奴哪个更适合约会",
        session_id="e2e-comparison",
        expect_answer_style="comparison",
        expect_answer_contains=["海底捞", "巴奴"],
        expect_metrics={"single_shop_mode": False},
    ),

    # ── 6. 单店工具：优惠券 ──
    E2ECase(
        case_id="E2E-10-tool-coupon",
        description="带店名的优惠券查询应触发工具",
        message="海底捞有券吗",
        session_id="e2e-tool-coupon",
        expect_answer_style=["coupon_only", "facet_multi"],
        expect_answer_contains=["券"],
        expect_metrics={"single_shop_mode": True},
    ),

    # ── 7. 单店工具：营业状态 ──
    E2ECase(
        case_id="E2E-11-tool-open",
        description="带店名的营业状态查询",
        message="海底捞现在营业吗",
        session_id="e2e-tool-open",
        expect_answer_style=["open_status_only", "facet_multi"],
        expect_answer_contains=["营业"],
        expect_metrics={"single_shop_mode": True},
    ),

    # ── 8. 单店工具：距离 ──
    E2ECase(
        case_id="E2E-12-tool-distance",
        description="带店名的距离查询",
        message="海底捞离我多远",
        session_id="e2e-tool-distance",
        expect_answer_style=["distance_only", "facet_multi"],
        expect_answer_contains=["距离", "海底捞"],
    ),

    # ── 9. 追问/Clarify ──
    E2ECase(
        case_id="E2E-13-clarify-no-shop",
        description="无明确店名的代词引用应触发追问",
        message="这家店有券吗",
        session_id="e2e-clarify-no-shop",
        expect_answer_style="clarification",
        expect_answer_contains=["店名", "具体"],
        expect_metrics={"clarification_needed": True},
    ),
    E2ECase(
        case_id="E2E-14-clarify-low-info",
        description="极低信息量输入应触发追问",
        message="。。。",
        session_id="e2e-clarify-low-info",
        expect_answer_contains=["补充", "店名"],
    ),

    # ── 10. 多维度混合查询 (facet_multi) ──
    E2ECase(
        case_id="E2E-15-facet-multi",
        description="同时问券和营业时间应走 facet_multi",
        message="海底捞有券吗，现在营业吗",
        session_id="e2e-facet-multi",
        expect_answer_style="facet_multi",
        expect_answer_contains=["海底捞"],
    ),

    # ── 11. 多轮会话：先锚定店铺再追问 ──
    E2ECase(
        case_id="E2E-16-multi-turn-pronoun",
        description="先问海底捞怎么样，再用代词追问券",
        message="这家店有券吗",
        session_id="e2e-multi-turn-pronoun",
        pre_messages=["海底捞怎么样"],
        expect_answer_style=["coupon_only", "facet_multi"],
        expect_answer_contains=["券"],
    ),

    # ── 12. 带 client_context 的单店查询 ──
    E2ECase(
        case_id="E2E-17-client-context-shop",
        description="客户端传入 shopId 上下文后查券",
        message="这家店有券吗",
        session_id="e2e-client-context-shop",
        extra_payload={"shopId": "12345", "shopName": "海底捞(水晶城店)"},
        expect_answer_style=["coupon_only", "facet_multi"],
        expect_answer_contains=["券"],
    ),
]


class E2ERoutingConvergenceTest(unittest.TestCase):
    """端到端路由收口验证测试"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()
        cls.results: list[dict[str, Any]] = []

    def _run_case(self, case: E2ECase) -> ChatStreamResult:
        """运行单个测试用例并返回结果"""
        # 先执行前置消息（多轮场景）
        for pre_msg in case.pre_messages:
            self.client.post_message(
                message=pre_msg,
                session_id=case.session_id,
                extra_payload=case.extra_payload,
            )

        # 执行主消息
        result = self.client.post_message(
            message=case.message,
            session_id=case.session_id,
            extra_payload=case.extra_payload,
        )
        return result

    def _assert_case(self, case: E2ECase, result: ChatStreamResult) -> list[str]:
        """对结果进行断言，返回失败信息列表"""
        failures: list[str] = []
        metrics = result.metrics or {}
        final_answer = result.final_answer or ""

        # 1. 检查 answer_style
        if case.expect_answer_style is not None:
            actual_style = str(metrics.get("answer_style") or "").strip()
            if isinstance(case.expect_answer_style, list):
                if actual_style not in case.expect_answer_style:
                    failures.append(
                        f"answer_style: expected one of {case.expect_answer_style}, got '{actual_style}'"
                    )
            else:
                if actual_style != case.expect_answer_style:
                    failures.append(
                        f"answer_style: expected '{case.expect_answer_style}', got '{actual_style}'"
                    )

        # 2. 检查 answer 包含关键词
        for keyword in case.expect_answer_contains:
            if keyword not in final_answer:
                failures.append(
                    f"final_answer missing keyword '{keyword}'. Answer: {final_answer[:200]}"
                )

        # 3. 检查 answer 不包含关键词
        for keyword in case.expect_answer_not_contains:
            if keyword in final_answer:
                failures.append(
                    f"final_answer should NOT contain '{keyword}'. Answer: {final_answer[:200]}"
                )

        # 4. 检查 metrics 字段值
        for key, expected_value in case.expect_metrics.items():
            actual_value = metrics.get(key)
            if actual_value != expected_value:
                failures.append(
                    f"metrics['{key}']: expected {expected_value!r}, got {actual_value!r}"
                )

        return failures

    # ---------------------------------------------------------------------------
    # 动态测试生成
    # ---------------------------------------------------------------------------


def _generate_test(case: E2ECase):
    """为每个 case 动态生成独立测试方法"""
    def test_method(self: E2ERoutingConvergenceTest):
        result = self._run_case(case)
        failures = self._assert_case(case, result)

        # 保存结果用于最终汇总
        test_result = {
            "case_id": case.case_id,
            "description": case.description,
            "message": case.message,
            "final_answer": (result.final_answer or "")[:300],
            "answer_style": str((result.metrics or {}).get("answer_style") or ""),
            "passed": not failures,
            "failures": failures,
            "metrics_snapshot": {
                k: (result.metrics or {}).get(k)
                for k in [
                    "answer_style", "single_shop_mode", "recommendation_mode",
                    "out_of_scope", "clarification_needed", "rag_mode",
                    "target_shop.source", "priority_source",
                ]
            },
        }
        self.results.append(test_result)

        if failures:
            self.fail(
                f"\n[{case.case_id}] {case.description}\n"
                f"  Message: {case.message}\n"
                f"  Answer:  {(result.final_answer or '')[:200]}\n"
                f"  Failures:\n" +
                "\n".join(f"    - {f}" for f in failures)
            )

    test_method.__doc__ = f"[{case.case_id}] {case.description}"
    return test_method


# 动态注册测试方法
for _case in E2E_CASES:
    _method_name = f"test_{_case.case_id.replace('-', '_').lower()}"
    setattr(E2ERoutingConvergenceTest, _method_name, _generate_test(_case))


class E2ESummaryTest(unittest.TestCase):
    """在所有 E2E 用例运行后打印汇总"""

    def test_z_print_summary(self) -> None:
        results = E2ERoutingConvergenceTest.results
        if not results:
            self.skipTest("No E2E results to summarize")
            return

        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        failed = total - passed

        print("\n" + "=" * 72)
        print(f"  端到端路由收口测试汇总: {passed}/{total} passed, {failed} failed")
        print("=" * 72)
        for r in results:
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            print(f"  {status} | {r['case_id']:<30} | style={r['answer_style']:<25}")
            if not r["passed"]:
                for f in r["failures"]:
                    print(f"         ↳ {f}")
        print("=" * 72)

        self.assertEqual(failed, 0, f"{failed}/{total} E2E routing cases failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
