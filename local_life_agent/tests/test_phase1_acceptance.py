"""Phase 1 acceptance scan for todo/01-08.

This file is intentionally strict. If a requirement is missing, the
test should fail so the gap is visible in QA.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from ..agent import run_agent
from ..domain.enums import ErrorCode, ToolResultStatus
from ..domain.schemas import (
    AnswerPlan,
    AllowedClaim,
    EvidenceItem,
    EvidencePack,
    ExecutionPlan,
    ResolveShopResult,
    ShopRef,
    ToolCallSpec,
    ToolResult,
    UserContext,
)
from ..tools.gateway import ToolCallGateway, dispatch_tool_call
from ..tools.executor import ToolExecutor


def test_schema_validation_requires_toolresult_shop_id():
    """ToolResult 的必填字段必须真的受约束。"""
    with pytest.raises(ValidationError):
        ToolResult.model_validate(
            {
                "call_id": "call_1",
                "tool_name": "get_shop_detail",
                "success": True,
                "result_status": "ok",
                "data": {"shop_id": "shop_sc_01"},
                "error_code": None,
                "error_message": "",
                "source": "mock",
                "degraded": False,
            }
        )


def test_shop_scoped_tool_requires_shop_id_but_search_shops_does_not():
    """按工具语义做条件必填，而不是把 shop_id 做成全局必填。"""
    with pytest.raises(ValidationError):
        ToolResult.model_validate(
            {
                "call_id": "call_2",
                "tool_name": "get_coupon_list",
                "success": True,
                "result_status": "empty",
                "data": [],
                "error_code": None,
                "error_message": "",
                "source": "mock",
                "degraded": False,
            }
        )

    result = ToolResult.model_validate(
        {
            "call_id": "call_3",
            "tool_name": "search_shops",
            "success": True,
            "result_status": "ok",
            "data": [],
            "error_code": None,
            "error_message": "",
            "source": "mock",
            "degraded": False,
        }
    )
    assert result.tool_name == "search_shops"
    assert result.shop_id == ""


def test_schema_roundtrip_and_nested_protocols():
    """实例化核心协议，验证 03/04 的深层字段存在。"""
    user_context = UserContext()
    assert user_context.location_name == "北京邮电大学"

    tool_call = ToolCallSpec(
        call_id="call_1",
        tool_name="get_coupon_list",
        args={"shop_id": "shop_sc_05"},
        target_shop_id="shop_sc_05",
        required=True,
        depends_on=[],
        timeout_ms=2000,
        group_id="group_1",
        max_parallelism=1,
    )
    execution_plan = ExecutionPlan(
        plan_id="plan_001",
        task_type="recommendation",
        tool_calls=[tool_call],
        target_shop_ids=["shop_sc_05"],
    )
    assert execution_plan.tool_calls[0].required is True
    assert execution_plan.tool_calls[0].depends_on == []

    evidence_item = EvidenceItem(
        evidence_id="evi_1",
        shop_id="shop_sc_05",
        shop_name="川味轩(知春路店)",
        facet="coupon",
        tool_name="get_coupon_list",
        call_id="call_1",
        result_status=ToolResultStatus.ok,
        field_path="data[0].title",
        value="满100减20",
        confidence=1.0,
        timestamp="2026-06-20T10:00:00Z",
        source_type="tool",
    )
    evidence_pack = EvidencePack(
        target_shop_ids=["shop_sc_05"],
        evidence_items=[evidence_item],
        unknown_items=[],
        forbidden_claims=["评分最高"],
        ranking_snapshot={"ranked": ["shop_sc_05"]},
        comparison_matrix={"rows": []},
    )
    assert evidence_pack.target_shop_ids == ["shop_sc_05"]
    assert evidence_pack.evidence_items[0].shop_id == "shop_sc_05"

    answer_plan = AnswerPlan(
        answer_type="recommendation",
        target_shop_ids=["shop_sc_05"],
        allowed_claims=[
            AllowedClaim(
                claim_id="claim_1",
                shop_id="shop_sc_05",
                facet="coupon",
                evidence_ids=["evi_1"],
                claim_type="coupon_present",
                value=True,
                verbalization_hint="现在有优惠券",
            )
        ],
        required_claims=[],
        must_mention_unknowns=[],
        forbidden_claims=["评分最高"],
        ranking_snapshot_id="snap_001",
        comparison_matrix_id="cmp_001",
        tone="neutral",
        fallback_template_type="safe_template",
    )
    assert answer_plan.allowed_claims[0].verbalization_hint == "现在有优惠券"


def test_resolve_shop_result_enforces_status_consistency():
    """ResolveShopResult 的状态一致性必须受验证。"""
    with pytest.raises(ValidationError):
        ResolveShopResult(status="AMBIGUOUS")

    with pytest.raises(ValidationError):
        ResolveShopResult(status="RESOLVED", confidence=0.9)

    resolved = ResolveShopResult(
        status="RESOLVED",
        resolved_shop=ShopRef(shop_id="shop_sc_05", shop_name="川味轩(知春路店)"),
        confidence=0.95,
        matched_by="exact",
    )
    assert resolved.resolved_shop.shop_id == "shop_sc_05"


def test_gateway_wraps_timeout_for_coupon_shop():
    """MockToolExecutor/Gateway 对 timeout 场景必须返回统一 ToolResult。"""
    class _TimeoutExecutor(ToolExecutor):
        async def execute(self, tool_def: dict, args: dict):
            raise TimeoutError("Coupon query timed out for shop_sc_06 (simulated)")

    timeout_gateway = ToolCallGateway(executor=_TimeoutExecutor())
    # Force dispatch_tool_call to traverse the timeout wrapping path explicitly.
    with patch("local_life_agent.tools.gateway.get_gateway", return_value=timeout_gateway):
        result = dispatch_tool_call("get_coupon_list", {"shop_id": "shop_sc_06"})
    assert result["success"] is False
    assert result["result_status"] == "unknown"
    assert result["error_code"] == ErrorCode.TOOL_TIMEOUT.value


def test_run_agent_returns_expected_dto_shape():
    """主入口返回值必须能稳定序列化为对外 DTO。"""
    response = run_agent("附近推荐火锅", session_id="phase1")
    payload = response.to_dict()
    assert {"answer_text", "trace_id", "session_id", "clarification", "cards", "debug"} <= set(payload)
    assert payload["trace_id"]
    assert payload["session_id"] == "phase1"
    assert isinstance(payload["debug"], dict)
