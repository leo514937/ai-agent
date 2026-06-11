from learning_agent_service.local_life.answer_structure_composer import (
    _compose_clarification,
    _compose_comparison,
)


class _Need:
    def __init__(self, *, missing_slots, intent="", clarify_reason="", constraints=None, raw_query=""):
        self.missing_slots = missing_slots
        self.intent = intent
        self.clarify_reason = clarify_reason
        self.constraints = constraints or {}
        self.raw_query = raw_query


def test_comparison_with_environment_taste_and_service():
    ranked_candidates = [
        {"shop_id": 1, "name": "海底捞", "structured_features": {"score": "4.5", "avg_price": "100"}},
        {"shop_id": 2, "name": "呷哺呷哺", "structured_features": {"score": "4.2", "avg_price": "60"}},
    ]
    grouped_claims = {
        1: ["环境优雅，装修现代", "服务热情周到", "口味稳定，锅底不错"],
        2: ["环境一般，比较吵闹", "口味不错，肉质新鲜"],
    }

    result = _compose_comparison("餐厅对比", ranked_candidates, grouped_claims, {})

    assert "海底捞" in result
    assert "呷哺呷哺" in result
    assert "环境氛围" in result
    assert "口味口感" in result
    assert "服务态度" in result
    assert "综合建议" in result


def test_compose_clarification_for_location_recommendation():
    result = _compose_clarification(
        "推荐结果",
        _Need(missing_slots=["location"], intent="recommendation"),
    )
    assert "城市" in result or "商圈" in result


def test_compose_clarification_for_reference_resolution_failed():
    result = _compose_clarification(
        "店铺澄清",
        _Need(missing_slots=["shop_name"], clarify_reason="reference_resolution_failed"),
    )
    assert "哪一家店" in result or "店名" in result


def test_compose_clarification_uses_priority_slot_first():
    result = _compose_clarification(
        "推荐结果",
        _Need(
            missing_slots=["shop_name", "location"],
            intent="recommendation",
            constraints={"clarification_priority_slot": "location"},
        ),
    )
    assert "城市" in result or "商圈" in result


def test_compose_clarification_uses_priority_and_avoids_repeating_same_slot():
    result = _compose_clarification(
        "推荐结果",
        _Need(
            missing_slots=["shop_name", "location"],
            intent="recommendation",
            constraints={
                "clarification_priority_slot": "location",
                "clarification_asked_slots": ["location"],
            },
        ),
    )
    assert "哪一家店" in result or "店名" in result


def test_comparison_prefers_scene_friendly_shop_for_date():
    ranked_candidates = [
        {"shop_id": 1, "name": "海底捞", "structured_features": {"score": "4.5", "avg_price": "100", "distance_km": "1.0"}},
        {"shop_id": 2, "name": "呷哺呷哺", "structured_features": {"score": "4.6", "avg_price": "90", "distance_km": "1.2"}},
    ]
    grouped_claims = {
        1: ["环境安静，氛围很好", "服务热情周到", "适合约会聊天"],
        2: ["环境一般，比较吵闹", "口味不错，出餐快"],
    }

    result = _compose_comparison(
        "餐厅对比",
        ranked_candidates,
        grouped_claims,
        {},
        _Need(
            missing_slots=[],
            intent="restaurant_comparison",
            raw_query="海底捞和呷哺呷哺哪个更适合约会",
            constraints={"scene_detected": "约会", "scene_preferred_facets": ["environment", "service"]},
        ),
    )

    assert "综合建议" in result
    assert "约会" in result
    assert "海底捞" in result
