"""Tests for dialog state machine."""
from learning_agent_service.local_life.dialog_state_machine import (
    DialogStateMachine,
    DialogState,
    DialogContext,
)


def test_initial_state():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    assert ctx.current_state == DialogState.IDLE
    assert ctx.transition_count == 0


def test_transition_missing_info():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    new_ctx = sm.transition(ctx, "missing_info")
    assert new_ctx.current_state == DialogState.CLARIFYING
    assert new_ctx.transition_count == 1


def test_transition_searching():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    ctx1 = sm.transition(ctx, "has_info")
    assert ctx1.current_state == DialogState.SEARCHING
    
    ctx2 = sm.transition(ctx1, "results_found")
    assert ctx2.current_state == DialogState.ANSWERING


def test_transition_comparison():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    ctx1 = sm.transition(ctx, "comparison_intent")
    assert ctx1.current_state == DialogState.COMPARING
    
    ctx2 = sm.transition(ctx1, "comparison_done")
    assert ctx2.current_state == DialogState.ANSWERING


def test_cannot_transition():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    # IDLE -> ANSWERING is not allowed
    assert not sm.can_transition(ctx, "answer_provided")


def test_max_transitions():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    # Exhaust transitions
    for _ in range(20):
        ctx = sm.transition(ctx, "has_info")
        ctx = sm.transition(ctx, "results_found")
        ctx = sm.transition(ctx, "answer_provided")
        ctx = sm.transition(ctx, "new_query")
        ctx = sm.transition(ctx, "has_info")
        ctx = sm.transition(ctx, "results_found")
        ctx = sm.transition(ctx, "answer_provided")
        ctx = sm.transition(ctx, "conversation_end")
    
    assert ctx.transition_count >= 20
    assert not sm.can_transition(ctx, "has_info")


def test_determine_trigger():
    sm = DialogStateMachine()
    ctx = sm.get_initial_state()
    
    trigger = sm.determine_trigger(ctx, has_clarification=True)
    assert trigger == "missing_info"
    
    trigger = sm.determine_trigger(ctx, is_comparison=True)
    assert trigger == "comparison_intent"