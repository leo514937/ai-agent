"""
BusinessObjectResolver 条件触发集成。

严格遵循执行顺序：
pre_hard_guard → RoutingAgent → classify_turn/slot → context_recovery
→ BusinessObjectResolver（条件触发） → RoutingPolicyValidator
"""

from __future__ import annotations

from typing import Any


def should_resolve_business_object(
    routing: Any,
    persistent: Any,
    turn_slots: dict[str, Any] | None = None,
    client_context: dict[str, Any] | None = None,
) -> bool:
    """判断是否需要调用 BusinessObjectResolver。

    Args:
        routing: RoutingDecision 对象
        persistent: PersistentSessionContext 对象
        turn_slots: 当前轮的 slots
        client_context: 客户端上下文

    Returns:
        True 表示需要调用 BusinessObjectResolver
    """
    # 1. 必须是本地生活域
    domain = getattr(routing, "domain", "general")
    if domain != "local_life":
        return False

    # 2. 问候、能力介绍、泛问不触发
    required_action = getattr(routing, "required_action", "no_op")
    if required_action in ("direct_answer", "reject", "no_op"):
        return False

    # 3. 检查 capability_line
    capability_line = getattr(routing, "capability_line", "direct")
    if capability_line in ("direct", "jailbreak", "clarify"):
        return False

    # 4. FacetPlan 中有需要店铺上下文的 facet
    facet_plan = getattr(routing, "facet_plan", [])
    needs_shop_context = any(
        getattr(facet, "required_target", "any") in ("single_shop", "multi_shop")
        for facet in facet_plan
    )
    if not needs_shop_context:
        return False

    # 5. multi_shop / recommendation 类场景也允许解析候选列表
    has_multi_shop_facet = any(
        getattr(facet, "required_target", None) == "multi_shop"
        for facet in facet_plan
    )
    if has_multi_shop_facet:
        return True

    # 6. single_shop 场景下，当前轮显式新店信号优先于 persistent
    if turn_slots and any(key in turn_slots for key in ("shop_id", "shop_name", "brand", "area")):
        return True
    if client_context and any(key in client_context for key in ("shopId", "shopName")):
        return True

    # 7. persistent.selected_shop_id 仅作为兜底上下文
    persistent_shop_id = getattr(persistent, "selected_shop_id", None)
    persistent_shop_name = getattr(persistent, "selected_shop_name", None)
    return persistent_shop_id is not None or persistent_shop_name is not None


def resolve_business_object_if_needed(
    state: dict[str, Any],
    business_object_resolver: Any,
) -> dict[str, Any]:
    """条件触发 BusinessObjectResolver（workflow 节点函数）。

    在 context_recovery 之后、RoutingPolicyValidator 之前调用。

    Args:
        state: workflow 状态
        business_object_resolver: BusinessObjectResolver 实例

    Returns:
        更新后的 state
    """
    # 1. 获取 routing decision
    turn = state.get("turn")
    if turn is None:
        return state

    routing = getattr(turn, "routing_decision", None)
    if routing is None:
        return state

    persistent = state.get("persistent")
    client_context = getattr(state.get("runtime"), "client_context", None) or {}

    # 2. 判断是否需要解析业务对象
    if not should_resolve_business_object(
        routing,
        persistent,
        turn_slots=getattr(turn, "slots", {}),
        client_context=client_context,
    ):
        return state

    # 3. 调用 BusinessObjectResolver
    resolved_shop = business_object_resolver.resolve(
        raw_query=getattr(turn, "raw_query", ""),
        shop_id=(
            getattr(turn, "slots", {}).get("shop_id")
            or client_context.get("shopId")
            or getattr(persistent, "selected_shop_id", None)
        ),
        shop_name=(
            getattr(turn, "slots", {}).get("shop_name")
            or client_context.get("shopName")
            or getattr(persistent, "selected_shop_name", None)
        ),
        brand=getattr(turn, "slots", {}).get("brand"),
        area=getattr(turn, "slots", {}).get("area"),
        intent_type=getattr(getattr(routing, "intent", None), "name", None),
    )

    # 4. 将 resolved_shop 注入 state
    runtime = state.get("runtime")
    if runtime is not None:
        extra = getattr(runtime, "extra", {})
        extra["resolved_shop"] = resolved_shop
        setattr(runtime, "extra", extra)

    return state
