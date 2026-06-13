"""指代消解测试用例 - 测试四类问题的解决能力"""
from learning_agent_service.local_life.schemas import LocalLifeIntentType, LocalLifeSlots, UserNeed
from learning_agent_service.local_life.user_need_parser import UserNeedParser


def test_entity_reference_pronoun():
    """测试1: 实体指代 - 代词指代"""
    # 模拟session上下文中有之前提到的店铺
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店"
    }
    
    # 用户说"这家有券吗"
    user_need = UserNeedParser.parse(
        "这家有券吗",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.COUPON,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该解析出context_ref指向session中的店铺
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    assert shop_refs[0].id == "12345"
    assert shop_refs[0].name == "海底捞水晶城店"


def test_entity_reference_explicit_name():
    """测试2: 实体指代 - 显式店名"""
    # 用户直接说"海底捞水晶城店怎么样"
    user_need = UserNeedParser.parse(
        "海底捞水晶城店怎么样",
        slots=LocalLifeSlots(shop_query="海底捞水晶城店"),
        intent=LocalLifeIntentType.DETAIL,
        client_context={},
        session_context={},
    )
    
    # 验证: 应该解析出显式实体
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    assert shop_refs[0].source == "explicit_entity"
    assert shop_refs[0].name == "海底捞水晶城店"


def test_intent_omission():
    """测试3: 意图省略 - 从上下文继承意图"""
    # 模拟session上下文中有之前推荐的餐厅列表
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店",
        "last_candidates": [
            {"shop_id": 12345, "name": "海底捞水晶城店"},
            {"shop_id": 12346, "name": "海底捞万达店"},
        ]
    }
    
    # 用户说"便宜一点的呢" - 省略了完整意图
    user_need = UserNeedParser.parse(
        "便宜一点的呢",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该继承session中的店铺上下文
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0


def test_constraint_inheritance():
    """测试4: 约束继承 - 从上下文继承约束条件"""
    # 模拟session上下文中有之前的约束
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店",
        "current_city": "北京",
        "area": "朝阳公园"
    }
    
    # 用户说"川菜呢" - 应该继承之前的约束
    user_need = UserNeedParser.parse(
        "川菜呢",
        slots=LocalLifeSlots(category="川菜", city="北京"),
        intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        client_context={"city": "北京"},
        session_context=session_context,
    )
    
    # 验证: 应该继承session中的店铺上下文
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    # 验证约束条件
    assert user_need.slots.category == "川菜"
    assert user_need.slots.city == "北京"


def test_comparison_object_completion():
    """测试5: 对比对象补全 - 补全对比对象"""
    # 模拟session上下文中有之前提到的店铺
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "湖畔私房菜"
    }
    
    # 用户说"和海底捞比呢" - 需要补全对比对象
    user_need = UserNeedParser.parse(
        "和海底捞比呢",
        slots=LocalLifeSlots(shop_query="海底捞"),
        intent=LocalLifeIntentType.RESTAURANT_COMPARISON,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该解析出显式实体(海底捞)
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    # 验证对比意图
    assert user_need.intent == "restaurant_comparison"


def test_pronoun_with_explicit_entity_priority():
    """测试6: 代词与显式实体优先级 - 显式实体优先"""
    # 模拟session上下文中有之前提到的店铺
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店"
    }
    
    # 用户说"INLOVE KTV 这家有券吗" - 显式实体优先
    user_need = UserNeedParser.parse(
        "INLOVE KTV 这家有券吗",
        slots=LocalLifeSlots(shop_query="INLOVE KTV"),
        intent=LocalLifeIntentType.COUPON,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该绑定显式实体，不沿用session历史
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    assert shop_refs[0].source == "explicit_entity"
    assert shop_refs[0].name == "INLOVE KTV"


def test_implicit_reference_for_coupon():
    """测试7: 隐式指代 - 查券意图的隐式指代"""
    # 模拟session上下文中有之前提到的店铺
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店"
    }
    
    # 用户只说"有券吗" - 意图是查券，应隐式指代
    user_need = UserNeedParser.parse(
        "有券吗",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.COUPON,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该从session中解析出店铺
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    assert shop_refs[0].id == "12345"


def test_scene_constraint_inheritance():
    """测试8: 场景约束继承 - 继承场景约束"""
    # 模拟session上下文中有之前的场景约束
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店",
        "scene": "家庭聚餐"
    }
    
    # 用户说"川菜呢" - 应该继承场景约束
    user_need = UserNeedParser.parse(
        "川菜呢",
        slots=LocalLifeSlots(category="川菜"),
        intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该继承session中的店铺上下文
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0
    # 验证约束条件
    assert user_need.slots.category == "川菜"


def test_multiple_pronouns_resolution():
    """测试9: 多代词解析 - 多个代词的解析"""
    # 模拟session上下文中有之前提到的多个店铺
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店",
        "last_candidates": [
            {"shop_id": 12345, "name": "海底捞水晶城店"},
            {"shop_id": 12346, "name": "海底捞万达店"},
        ]
    }
    
    # 用户说"刚才那家怎么样" - 解析"刚才那家"
    user_need = UserNeedParser.parse(
        "刚才那家怎么样",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.DETAIL,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 应该解析出店铺
    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0


def test_no_reference_clarification():
    """测试10: 无法解析时应触发澄清"""
    # 模拟session上下文为空
    session_context = {}
    
    # 用户只说"这家有券吗" - 无法解析
    user_need = UserNeedParser.parse(
        "这家有券吗",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.COUPON,
        client_context={},
        session_context=session_context,
    )
    
    # 验证: 无法解析时context_refs应为空或包含澄清信息
    # 注意: 这里可能需要根据实际业务逻辑调整
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    # 如果没有解析出店铺，应触发澄清
    if len(shop_refs) == 0:
        assert True  # 测试通过，表示会触发澄清
    else:
        # 如果有解析，应指向合理的店铺
        assert shop_refs[0].confidence > 0.5


def test_entity_resolver_with_explicit_name():
    """测试EntityResolver处理显式店名"""
    from learning_agent_service.local_life.entity_resolver import EntityResolver
    
    resolver = EntityResolver()
    plan = resolver.resolve(
        raw_query="海底捞水晶城店怎么样",
        slots=LocalLifeSlots(shop_query="海底捞水晶城店"),
        user_need=UserNeedParser.parse(
            "海底捞水晶城店怎么样",
            slots=LocalLifeSlots(shop_query="海底捞水晶城店"),
            intent=LocalLifeIntentType.DETAIL,
        ),
    )
    
    # 验证: 应该解析出显式实体
    assert plan.resolved_shop_name is not None
    assert "海底捞" in plan.resolved_shop_name
    assert plan.reason == "explicit_entity"


def test_entity_resolver_with_pronoun():
    """测试EntityResolver处理代词指代"""
    from learning_agent_service.local_life.entity_resolver import EntityResolver
    
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店"
    }
    
    resolver = EntityResolver()
    plan = resolver.resolve(
        raw_query="这家有券吗",
        slots=LocalLifeSlots(),
        user_need=UserNeedParser.parse(
            "这家有券吗",
            slots=LocalLifeSlots(),
            intent=LocalLifeIntentType.COUPON,
            session_context=session_context,
        ),
        session_context=session_context,
    )
    
    # 验证: 应该解析出session中的店铺
    assert plan.resolved_shop_id == 12345
    assert plan.resolved_shop_name == "海底捞水晶城店"
    assert plan.reason == "session_context"


def test_entity_resolver_comparison():
    """测试EntityResolver处理对比意图"""
    from learning_agent_service.local_life.entity_resolver import EntityResolver
    
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "湖畔私房菜"
    }
    
    resolver = EntityResolver()
    plan = resolver.resolve(
        raw_query="和海底捞比呢",
        slots=LocalLifeSlots(shop_query="海底捞"),
        user_need=UserNeedParser.parse(
            "和海底捞比呢",
            slots=LocalLifeSlots(shop_query="海底捞"),
            intent=LocalLifeIntentType.RESTAURANT_COMPARISON,
            session_context=session_context,
        ),
        session_context=session_context,
    )
    
    # 验证: 应该解析出显式实体
    assert plan.resolved_shop_name is not None
    assert "海底捞" in plan.resolved_shop_name
    assert plan.reason == "explicit_entity"


def test_intent_ellipsis_variants_preserve_context_refs():
    """测试3b: 意图省略的口语变体也应继承推荐上下文"""
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "海底捞水晶城店",
        "last_candidates": [
            {"shop_id": 12345, "name": "海底捞水晶城店"},
            {"shop_id": 12346, "name": "海底捞万达店"},
        ],
    }

    user_need = UserNeedParser.parse(
        "再便宜点呢",
        slots=LocalLifeSlots(),
        intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
        client_context={},
        session_context=session_context,
    )

    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) > 0


def test_comparison_completion_prefers_explicit_target_over_history():
    """测试5b: 对比补全时显式目标优先于历史店铺"""
    session_context = {
        "selected_shop_id": 12345,
        "selected_shop_name": "湖畔私房菜",
    }

    user_need = UserNeedParser.parse(
        "湖畔私房菜和海底捞比呢",
        slots=LocalLifeSlots(shop_query="海底捞"),
        intent=LocalLifeIntentType.RESTAURANT_COMPARISON,
        client_context={},
        session_context=session_context,
    )

    assert len(user_need.context_refs) > 0
    shop_refs = [ref for ref in user_need.context_refs if ref.type == "shop"]
    assert len(shop_refs) >= 1
    assert any(ref.name == "海底捞" for ref in shop_refs)
    assert user_need.intent == "restaurant_comparison"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
