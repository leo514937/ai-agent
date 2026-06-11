from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.local_life.schemas import LocalLifeSlots


def test_route_exposes_scene_preference_and_prioritizes_scene_fit_role():
    decision = LocalLifeQueryRouter().route(
        "适合商务宴请的餐厅推荐",
        slots=LocalLifeSlots(),
        intent="restaurant_recommendation",
    )

    assert decision.extra.get("scene_detected") == "商务宴请"
    assert "service" in decision.extra.get("scene_preferred_facets", [])
    assert decision.preferred_roles
    assert decision.preferred_roles[0] == "merchant_scene_fit"
