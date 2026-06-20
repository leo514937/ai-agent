"""Comprehensive verification of the state transition & session write strategy.

Covers every row in the two tables from `todo/02_状态转移与路由决策表.md`:

  §1 — State transition table (12 rules)
  §2 — Session write strategy  (8 scenarios)

Run:  python -m pytest local_life_agent/tests/test_02_state_transition.py -v
"""

from ..engine.nodes import ExecutionNode, NodeResult, RoutingResult
from ..engine.transition import (
    route,
    route_with_status,
    TRANSITION_TABLE,
    NORMAL_FLOW,
)
from ..engine.session_write import (
    SessionScenario,
    get_directive,
    resolve_scenario,
)
from ..domain.state import SessionWriteDirective


# ===================================================================
# §1: State Transition Table — 12 rules
# ===================================================================

# --- Rule 1: semantic_parse + json_parse_fail → CLARIFY_RESPONSE, emit=True ---
def test_rule_1_semantic_parse_json_fail():
    result = route_with_status(ExecutionNode.SEMANTIC_PARSE, "json_parse_fail")
    assert result.next_node == ExecutionNode.CLARIFY_RESPONSE
    assert result.emit_response is True
    assert result.session_write is None


# --- Rule 2: semantic_parse + task_type_invalid → FRAME_VALIDATOR, emit=True ---
def test_rule_2_semantic_parse_task_type_invalid():
    result = route_with_status(ExecutionNode.SEMANTIC_PARSE, "task_type_invalid")
    assert result.next_node == ExecutionNode.FRAME_VALIDATOR
    assert result.emit_response is True
    assert result.session_write is None


# --- Rule 3: resolve_shop + RESOLVED → TASK_PLAN, emit=False, write current_shop ---
def test_rule_3_resolve_shop_resolved():
    result = route_with_status(ExecutionNode.TARGET_RESOLVE, "RESOLVED")
    assert result.next_node == ExecutionNode.TASK_PLAN
    assert result.emit_response is False
    assert result.session_write is not None
    assert "current_shop" in result.session_write.set_fields


# --- Rule 4: resolve_shop + AMBIGUOUS → CLARIFY_RESPONSE, emit=True, write pending ---
def test_rule_4_resolve_shop_ambiguous():
    result = route_with_status(ExecutionNode.TARGET_RESOLVE, "AMBIGUOUS")
    assert result.next_node == ExecutionNode.CLARIFY_RESPONSE
    assert result.emit_response is True
    assert result.session_write is not None
    assert "pending_clarification" in result.session_write.set_fields


# --- Rule 5: resolve_shop + LOW_CONFIDENCE → CLARIFY_RESPONSE, emit=True, write pending ---
def test_rule_5_resolve_shop_low_confidence():
    result = route_with_status(ExecutionNode.TARGET_RESOLVE, "LOW_CONFIDENCE")
    assert result.next_node == ExecutionNode.CLARIFY_RESPONSE
    assert result.emit_response is True
    assert result.session_write is not None
    assert "pending_clarification" in result.session_write.set_fields


# --- Rule 6: resolve_shop + NOT_FOUND → FALLBACK_ANSWER, emit=True ---
def test_rule_6_resolve_shop_not_found():
    result = route_with_status(ExecutionNode.TARGET_RESOLVE, "NOT_FOUND")
    assert result.next_node == ExecutionNode.FALLBACK_ANSWER
    assert result.emit_response is True
    # NOT_FOUND: no session write specified (no scenario set on the rule)
    # The doc says: "不写 current_shop" — which is the default behavior when
    # no session_write directive is provided.


# --- Rule 7: tool_execute + required_tool_failed → FALLBACK_ANSWER, emit=True ---
def test_rule_7_tool_execute_required_failed():
    result = route_with_status(ExecutionNode.TOOL_EXECUTE, "required_tool_failed")
    assert result.next_node == ExecutionNode.FALLBACK_ANSWER
    assert result.emit_response is True
    assert result.session_write is not None


# --- Rule 8: tool_execute + optional_tool_failed → EVIDENCE_BUILD, emit=True ---
def test_rule_8_tool_execute_optional_failed():
    result = route_with_status(ExecutionNode.TOOL_EXECUTE, "optional_tool_failed")
    assert result.next_node == ExecutionNode.EVIDENCE_BUILD
    assert result.emit_response is True
    assert result.session_write is None


# --- Rule 9: tool_execute + circuit_open → FALLBACK_ANSWER, emit=True ---
def test_rule_9_tool_execute_circuit_open():
    result = route_with_status(ExecutionNode.TOOL_EXECUTE, "circuit_open")
    assert result.next_node == ExecutionNode.FALLBACK_ANSWER
    assert result.emit_response is True
    assert result.session_write is not None


# --- Rule 10: answer_verify + pass → FINAL_RESPONSE_BUILD, emit=True ---
def test_rule_10_answer_verify_pass():
    result = route_with_status(ExecutionNode.ANSWER_VERIFY, "pass")
    assert result.next_node == ExecutionNode.FINAL_RESPONSE_BUILD
    assert result.emit_response is True
    assert result.session_write is None


# --- Rule 11: answer_verify + rewrite_needed + count < 2 → REWRITE, emit=False ---
def test_rule_11_answer_verify_rewrite_needed():
    result = route_with_status(ExecutionNode.ANSWER_VERIFY, "rewrite_needed")
    assert result.next_node == ExecutionNode.REWRITE
    assert result.emit_response is False
    assert result.session_write is None


# --- Rule 12: answer_verify + rewrite_exhausted → FALLBACK_ANSWER, emit=True ---
def test_rule_12_answer_verify_rewrite_exhausted():
    result = route_with_status(ExecutionNode.ANSWER_VERIFY, "rewrite_exhausted")
    assert result.next_node == ExecutionNode.FALLBACK_ANSWER
    assert result.emit_response is True
    assert result.session_write is None


# ===================================================================
# Verify that ALL 12 rules in TRANSITION_TABLE are tested
# ===================================================================

def test_all_transition_rules_covered():
    """Ensures every rule in TRANSITION_TABLE has a corresponding test.

    We simply check that the number of rules equals the expected count (12).
    If a rule is added or removed, this test catches it.
    """
    assert len(TRANSITION_TABLE) == 12, (
        f"Expected 12 transition rules, got {len(TRANSITION_TABLE)}. "
        "Update tests when the table changes."
    )


# ===================================================================
# §2: Session Write Strategy — 8 scenarios
# ===================================================================

# --- Scenario 1: 单店查券成功 ---
def test_session_scenario_single_shop_coupon_ok():
    directive = get_directive(SessionScenario.SINGLE_SHOP_COUPON_OK)
    assert "current_shop" in directive.set_fields
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 2: 单店多facet成功 ---
def test_session_scenario_single_shop_multi_facet_ok():
    directive = get_directive(SessionScenario.SINGLE_SHOP_MULTI_FACET_OK)
    assert "current_shop" in directive.set_fields
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 3: 附近推荐成功 ---
def test_session_scenario_nearby_recommendation_ok():
    directive = get_directive(SessionScenario.NEARBY_RECOMMENDATION_OK)
    assert "last_recommendation_list" in directive.set_fields
    assert "current_shop" in directive.clear_fields
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 4: 多店对比成功 ---
def test_session_scenario_comparison_ok():
    directive = get_directive(SessionScenario.COMPARISON_OK)
    assert len(directive.set_fields) == 0  # 一般不写
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 5: resolve_shop AMBIGUOUS ---
def test_session_scenario_resolve_shop_ambiguous():
    directive = get_directive(SessionScenario.RESOLVE_SHOP_AMBIGUOUS)
    assert "pending_clarification" in directive.set_fields
    assert len(directive.clear_fields) == 0  # DO NOT clear


# --- Scenario 6: 用户澄清成功 ---
def test_session_scenario_clarification_reply_ok():
    directive = get_directive(SessionScenario.CLARIFICATION_REPLY_OK)
    assert len(directive.set_fields) == 0  # depends on original task
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 7: 用户换话题 ---
def test_session_scenario_topic_switch():
    directive = get_directive(SessionScenario.TOPIC_SWITCH)
    assert len(directive.set_fields) == 0  # depends on new task
    assert "pending_clarification" in directive.clear_fields


# --- Scenario 8: 工具 unknown/failed ---
def test_session_scenario_tool_unknown_failed():
    directive = get_directive(SessionScenario.TOOL_UNKNOWN_FAILED)
    assert len(directive.set_fields) == 0  # no update to target/reco
    assert "pending_clarification" in directive.clear_fields


# ===================================================================
# resolve_scenario() routing
# ===================================================================

def test_resolve_scenario_mapping():
    """Verify that resolve_scenario maps inputs to correct scenarios."""
    # Successful task branches
    assert resolve_scenario("single_shop_query", "RESOLVED") == SessionScenario.SINGLE_SHOP_COUPON_OK
    assert resolve_scenario("coupon_query", "RESOLVED") == SessionScenario.SINGLE_SHOP_COUPON_OK
    assert resolve_scenario("recommendation", "RESOLVED") == SessionScenario.NEARBY_RECOMMENDATION_OK
    assert resolve_scenario("comparison", "RESOLVED") == SessionScenario.COMPARISON_OK

    # AMBIGUOUS resolve
    assert resolve_scenario("single_shop_query", "AMBIGUOUS") == SessionScenario.RESOLVE_SHOP_AMBIGUOUS

    # Clarification reply
    assert resolve_scenario(None, None, is_clarification_reply=True) == SessionScenario.CLARIFICATION_REPLY_OK

    # Topic switch
    assert resolve_scenario(None, None, is_topic_switch=True) == SessionScenario.TOPIC_SWITCH

    # Tool failure
    assert resolve_scenario("single_shop_query", "RESOLVED", tool_failure_severity="required") == SessionScenario.TOOL_UNKNOWN_FAILED
    assert resolve_scenario("single_shop_query", "RESOLVED", tool_failure_severity="circuit_open") == SessionScenario.TOOL_UNKNOWN_FAILED

    # Default fallback
    assert resolve_scenario(None, None) == SessionScenario.TOOL_UNKNOWN_FAILED


# ===================================================================
# SessionWriteDirective clone isolation
# ===================================================================

def test_directive_clone_isolation():
    """Ensure get_directive returns independent copies."""
    d1 = get_directive(SessionScenario.SINGLE_SHOP_COUPON_OK)
    d2 = get_directive(SessionScenario.SINGLE_SHOP_COUPON_OK)
    d1.set_fields["current_shop"] = {"shop_id": "test"}
    assert d2.set_fields["current_shop"] is None  # unchanged


# ===================================================================
# Normal flow coverage
# ===================================================================

def test_normal_flow_full_path():
    """Traverse the happy-path normal flow end-to-end."""
    sequence = [
        ExecutionNode.RECEIVE_INPUT,
        ExecutionNode.LOAD_SESSION_STATE,
        ExecutionNode.CHECK_PENDING_CLARIFICATION,
        ExecutionNode.BASIC_INPUT_VALIDATE,
        ExecutionNode.NORMALIZE_TEXT,
        ExecutionNode.HARD_GUARD,
        ExecutionNode.TOP_INTENT_ROUTER,
        ExecutionNode.SEMANTIC_PARSE,
        ExecutionNode.SLOT_EXTRACTOR,
        ExecutionNode.CONTEXT_RECOVERY,
        ExecutionNode.TARGET_RESOLVE,
        ExecutionNode.TASK_PLAN,
        ExecutionNode.FACET_PLAN,
        ExecutionNode.PLAN_VALIDATOR,
        ExecutionNode.TOOL_EXECUTE,
        ExecutionNode.EVIDENCE_BUILD,
        ExecutionNode.ANSWER_PLAN_BUILD,
        ExecutionNode.ANSWER_GENERATE,
        ExecutionNode.ANSWER_VERIFY,
        ExecutionNode.FINAL_RESPONSE_BUILD,
        ExecutionNode.STATE_UPDATE_PLAN,
        ExecutionNode.PERSIST_SESSION_STATE,
        ExecutionNode.EMIT_RESPONSE,
    ]

    for i, node in enumerate(sequence):
        result = route(NodeResult(node=node, status="ok"))
        if i + 1 < len(sequence):
            expected_next = sequence[i + 1]
            assert result.next_node == expected_next, (
                f"Node {node.value}: expected next={expected_next.value}, "
                f"got {result.next_node.value if result.next_node else None}"
            )
        else:
            # EMIT_RESPONSE is terminal
            assert result.next_node is None


# ===================================================================
# Branch path coverage
# ===================================================================

def test_rewrite_loop():
    """REWRITE → ANSWER_GENERATE via normal flow."""
    result = route(NodeResult(node=ExecutionNode.REWRITE, status="ok"))
    assert result.next_node == ExecutionNode.ANSWER_GENERATE


def test_clarify_merges_to_state_update():
    """CLARIFY_RESPONSE → STATE_UPDATE_PLAN via normal flow."""
    result = route(NodeResult(node=ExecutionNode.CLARIFY_RESPONSE, status="ok"))
    assert result.next_node == ExecutionNode.STATE_UPDATE_PLAN


def test_fallback_merges_to_state_update():
    """FALLBACK_ANSWER → STATE_UPDATE_PLAN via normal flow."""
    result = route(NodeResult(node=ExecutionNode.FALLBACK_ANSWER, status="ok"))
    assert result.next_node == ExecutionNode.STATE_UPDATE_PLAN
