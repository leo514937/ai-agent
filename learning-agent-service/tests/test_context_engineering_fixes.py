# -*- coding: utf-8 -*-
from learning_agent_service.local_life.schemas import LocalLifeSlots, UserNeed, ContextRef
from learning_agent_service.local_life.context_arbitration import ContextArbitration
from learning_agent_service.local_life.entity_resolver import EntityResolver


def test_generic_slot_overwriting_prevention():
    # 测试：泛代词（低特异性，如“这家店”）不应该静默覆盖 pending 状态中的高特异性实体（如“Mamala”）
    arbitrator = ContextArbitration()
    
    # 模拟 pending user need 里已经有一个具体的 shop_query = "Mamala"
    pending_source = {
        "slots": {
            "category": "美食",
            "shop_query": "Mamala"
        }
    }
    
    # 用户当前轮次只抽取出低特异性的“这家店”作为 shop_query
    current_slots = LocalLifeSlots.model_validate({
        "shop_query": "这家店",
        "category": "美食"
    })
    
    user_need = UserNeed.model_validate({
        "raw_query": "这家店有券吗",
        "resolved_query": "这家店有券吗",
        "intent": "local_life_recommend",
        "slots": current_slots.model_dump(mode="json"),
        "constraints": {},
        "required_facets": [],
        "context_refs": []
    })
    
    result = arbitrator.arbitrate(
        raw_query="这家店有券吗",
        slots=current_slots,
        user_need=user_need,
        session_context={"pending_user_need": pending_source}
    )
    
    merged_slots = result["user_need"].slots
    # 合并后，“这家店”应该被具体的“Mamala”成功保留和继承，而不是被“这家店”覆盖
    assert merged_slots.shop_query == "Mamala"


def test_cross_slot_geographical_cascading_reset():
    # 测试：地缘空间级联失效。一旦城市切换（上海 -> 北京），必须自动失效并清空下属的地缘槽位（如徐家汇）
    arbitrator = ContextArbitration()
    
    pending_source = {
        "slots": {
            "city": "上海",
            "shop_query": "徐家汇",
            "location": {"city": "上海", "lat": 31.2, "lng": 121.4}
        }
    }
    
    # 本轮抽取中，城市明确变更为“北京”
    current_slots = LocalLifeSlots.model_validate({
        "city": "北京"
    })
    
    user_need = UserNeed.model_validate({
        "raw_query": "给我推荐北京的",
        "resolved_query": "给我推荐北京的",
        "intent": "local_life_recommend",
        "slots": current_slots.model_dump(mode="json"),
        "constraints": {},
        "required_facets": [],
        "context_refs": []
    })
    
    result = arbitrator.arbitrate(
        raw_query="给我推荐北京的",
        slots=current_slots,
        user_need=user_need,
        session_context={"pending_user_need": pending_source}
    )
    
    merged_slots = result["user_need"].slots
    assert merged_slots.city == "北京"
    # 发生了城市切换，下级的“徐家汇”应该在合并时被清空，防止“北京徐家汇”矛盾
    assert merged_slots.shop_query is None or merged_slots.shop_query == ""
    assert merged_slots.location.lat is None


def test_list_type_slots_collision_override():
    # 测试：冲突消解。用户正向 preferences 覆盖负向 avoid 中冲突的元素（如避辣 vs 喜欢吃辣）
    arbitrator = ContextArbitration()
    
    pending_source = {
        "slots": {
            "avoid": ["辣"]
        }
    }
    
    current_slots = LocalLifeSlots.model_validate({
        "preferences": ["川菜", "微辣"]
    })
    
    user_need = UserNeed.model_validate({
        "raw_query": "我想吃微辣川菜",
        "resolved_query": "我想吃微辣川菜",
        "intent": "local_life_recommend",
        "slots": current_slots.model_dump(mode="json"),
        "constraints": {},
        "required_facets": [],
        "context_refs": []
    })
    
    # 模拟用户当前说“我还是吃微辣川菜吧”
    result = arbitrator.arbitrate(
        raw_query="我想吃微辣川菜",
        slots=current_slots,
        user_need=user_need,
        session_context={"pending_user_need": pending_source}
    )
    
    merged_slots = result["user_need"].slots
    # preferences 成功合并
    assert "川菜" in merged_slots.preferences
    # 发生正向 preferences 冲突消解，avoid 中的“辣”被剔除
    assert "辣" not in merged_slots.avoid


def test_intent_drift_guard_wipe():
    # 测试：意图漂移保护。一旦品类发生大范围意图漂移，自动清空 pending，阻止合并
    arbitrator = ContextArbitration()
    
    # 模拟 pending 挂起的是烤肉
    pending_source = {
        "slots": {
            "category": "烤肉",
            "price": {"per_person_max": 100}
        }
    }
    
    # 用户本轮却想订高铁票或问 KTV
    current_slots = LocalLifeSlots.model_validate({
        "category": "高铁"
    })
    
    user_need = UserNeed.model_validate({
        "raw_query": "帮我订一张去北京的高铁票",
        "resolved_query": "帮我订一张去北京的高铁票",
        "intent": "navigation",
        "slots": current_slots.model_dump(mode="json"),
        "constraints": {},
        "required_facets": [],
        "context_refs": []
    })
    
    result = arbitrator.arbitrate(
        raw_query="帮我订一张去北京的高铁票",
        slots=current_slots,
        user_need=user_need,
        session_context={"pending_user_need": pending_source}
    )
    
    merged_slots = result["user_need"].slots
    # 发生了意图漂移，合并应该被完全阻止，pending 被 wipe 擦除，仅保留本轮
    assert result["restored_pending_need"] is False
    assert merged_slots.category == "高铁"
    assert merged_slots.price.per_person_max is None


def test_pronoun_explicit_prioritization():
    # 测试：代词优先级消解。口头显式代词的优先级应该高于静态页面绑定 client_context
    resolver = EntityResolver()
    
    # 模拟页面关联了 shop:3，但用户口头指示的是 shop:4
    context_refs = [
        ContextRef(type="shop", id="3", name="Mamala西餐厅", source="client_context"),
        ContextRef(type="shop", id="4", name="水晶城KTV", source="explicit_entity")
    ]
    
    slots = LocalLifeSlots.model_validate({
        "shop_query": "这家店"
    })
    
    user_need = UserNeed.model_validate({
        "raw_query": "刚才那家店水晶城店有券吗",
        "resolved_query": "刚才那家店水晶城店有券吗",
        "intent": "local_life_shop_detail",
        "slots": slots.model_dump(mode="json"),
        "constraints": {},
        "required_facets": [],
        "context_refs": context_refs
    })
    
    contract = resolver.resolve(
        raw_query="刚才那家店水晶城店有券吗",
        slots=slots,
        user_need=user_need,
        session_context={}
    )
    
    # 虽然 client_context (shop:3) 排在 context_refs 第一位，但由于 explicit_entity (shop:4)
    # 拥有绝对的最高优先级，解析绑定的 ID 应为 shop:4
    assert contract.resolved_shop_id == 4
    assert contract.resolved_shop_name == "水晶城KTV"
