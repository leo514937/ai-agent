from learning_agent_service.local_life.schemas import LocalLifeIntentType, LocalLifeSlots
from learning_agent_service.local_life.user_need_parser import UserNeedParser


def test_parse_adds_scene_detection_and_preferred_facets_to_constraints():
    user_need = UserNeedParser.parse(
        "附近适合商务宴请的餐厅推荐",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        client_context={},
        session_context={},
    )

    assert user_need.constraints.get("scene_detected") == "商务宴请"
    assert "service" in user_need.constraints.get("scene_preferred_facets", [])
    assert user_need.constraints.get("clarification_priority_slot") == "location"
