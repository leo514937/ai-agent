from learning_agent_service.local_life.clarification_strategy import ClarificationStrategy


def test_should_avoid_repeat_clarification():
    assert ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=["shop_name"],
    )

    assert not ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=[],
    )

    assert ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="shop_name",
        asked_slots=[],
        context_shop="海底捞",
    )


def test_should_avoid_repeat_clarification_for_consecutive_turns():
    assert ClarificationStrategy.should_avoid_repeat_clarification(
        current_slot="location",
        asked_slots=[],
        last_clarification_turn=3,
        current_turn=4,
    )


def test_get_clarification_priority():
    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="recommendation",
        has_context_shop=False,
    )
    assert priority == "location"

    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="recommendation",
        has_context_shop=True,
    )
    assert priority == "location"

    priority = ClarificationStrategy.get_clarification_priority(
        missing_slots=["shop_name", "location"],
        intent="merchant_detail",
        has_context_shop=False,
    )
    assert priority == "shop_name"
