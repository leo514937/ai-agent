from __future__ import annotations

from datetime import datetime, timezone

import _bootstrap  # noqa: F401

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext, TurnUnderstandingRequest
from learning_agent_service.rag.heuristics import HeuristicIntentGate
from learning_agent_service.local_life.context_recovery import recover_follow_up_context
from learning_agent_service.memory.models import SessionUpdate
from learning_agent_service.memory.promotion import SessionMemoryUpdater


def _build_request(message: str, persistent: PersistentSessionContext | None = None) -> TurnUnderstandingRequest:
    command = ChatTurnCommand(
        trace_id="trace-semantic",
        session_id="session-semantic",
        turn_id="turn-semantic",
        user_id="user-semantic",
        message=message,
        topic_hint="本地生活",
        response_mode="detailed",
        client_context={},
    )
    return TurnUnderstandingRequest(command=command, persistent=persistent or PersistentSessionContext())


def test_semantic_gate_bypasses_llm_for_complex_mixed_follow_up() -> None:
    gate = HeuristicIntentGate()
    persistent = PersistentSessionContext(
        current_topic="湖畔私房菜",
        current_shop="湖畔私房菜",
        current_shop_anchor={"name": "湖畔私房菜", "shop_id": 1001},
        current_scene="family_dinner",
        current_constraints={"scene": "family_dinner", "city": "北京"},
        selected_shop_id=1001,
        selected_shop_name="湖畔私房菜",
    )

    decision = gate.fast_decide(_build_request("和海底捞比，便宜一点的呢", persistent))

    assert decision is None


def test_semantic_gate_attaches_context_for_simple_follow_up() -> None:
    gate = HeuristicIntentGate()
    persistent = PersistentSessionContext(
        current_topic="海底捞水晶城店",
        current_shop="海底捞水晶城店",
        current_shop_anchor={"name": "海底捞水晶城店", "shop_id": 2002},
        selected_shop_id=2002,
        selected_shop_name="海底捞水晶城店",
    )

    decision = gate.fast_decide(_build_request("这家有券吗？", persistent))

    assert decision is not None
    assert decision.extra["follow_up_kind"] == "entity_reference"
    assert decision.extra["semantic_context"]["anchor_shop"]["name"] == "海底捞水晶城店"


def test_session_memory_updater_preserves_dialog_and_anchor_state() -> None:
    updater = SessionMemoryUpdater()
    current = PersistentSessionContext(
        current_topic="湖畔私房菜",
        current_shop="湖畔私房菜",
        current_shop_anchor={"name": "湖畔私房菜", "shop_id": 1001},
        current_scene="date",
        current_constraints={"scene": "date", "price": "budget"},
        dialog_state="follow_up",
        dialog_task="recommendation",
        dialog_intent="recommend",
        dialog_comparison_targets=["海底捞"],
        dialog_pending_slots=["price_range"],
        dialog_transition_count=2,
        confirmed_facts=["喜欢安静"],
        user_preferences={"avoid": ["辣"]},
    )
    update = SessionUpdate(
        current_topic="湖畔私房菜",
        current_shop="湖畔私房菜",
        current_shop_anchor={"name": "湖畔私房菜", "shop_id": 1001, "source": "follow_up"},
        current_scene="date",
        current_constraints={"scene": "date", "price": "budget", "city": "北京"},
        dialog_state="comparing",
        dialog_task="comparison",
        dialog_intent="compare",
        dialog_comparison_targets=("海底捞", "巴奴"),
        dialog_pending_slots=("shop_name",),
        dialog_transition_count=3,
        confirmed_facts=("喜欢安静",),
        summary_version=3,
        summary_updated_at=datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc),
    )

    merged = updater.merge_context(current, update)

    assert merged.current_shop_anchor["shop_id"] == 1001
    assert merged.current_constraints["city"] == "北京"
    assert merged.dialog_state == "comparing"
    assert merged.dialog_task == "comparison"
    assert merged.dialog_intent == "compare"
    assert merged.dialog_comparison_targets == ("海底捞", "巴奴")
    assert merged.dialog_pending_slots == ("shop_name",)
    assert merged.dialog_transition_count == 3
    assert merged.confirmed_facts == ("喜欢安静",)


def test_follow_up_context_extracts_comparison_and_constraints() -> None:
    recovery = recover_follow_up_context(
        "和海底捞比，便宜一点的呢",
        session_context={
            "current_shop": "湖畔私房菜",
            "current_shop_anchor": {"name": "湖畔私房菜", "shop_id": 1001},
            "current_constraints": {"scene": "family_dinner", "city": "北京"},
        },
    )

    assert recovery.follow_up_kind == "comparison_completion"
    assert recovery.anchor_shop is not None
    assert recovery.anchor_shop.name == "湖畔私房菜"
    assert any(target.name == "海底捞" for target in recovery.comparison_targets)
    assert recovery.inherited_constraints["scene"] == "family_dinner"
