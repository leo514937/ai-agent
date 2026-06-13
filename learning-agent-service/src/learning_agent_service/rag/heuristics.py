from __future__ import annotations

from dataclasses import dataclass

from learning_agent_service.domain import (
    FastDecision,
    TurnUnderstandingRequest,
    TurnUnderstandingResult,
)
from learning_agent_service.domain.enums import IntentType, OutputStyle, TurnDecision

from .domain_rules import (
    DomainRulesConfig,
    _BUILTIN_DOMAIN_RULES,
    load_domain_rules_config,
    get_all_domain_tokens,
)

_domain_rules: DomainRulesConfig | None = None


def _get_domain_rules() -> DomainRulesConfig:
    global _domain_rules
    if _domain_rules is None:
        try:
            _domain_rules = load_domain_rules_config()
        except Exception:
            _domain_rules = _BUILTIN_DOMAIN_RULES
    return _domain_rules


def _rule_tokens(attr: str) -> tuple[str, ...]:
    rules = _get_domain_rules()
    return getattr(rules, attr, ())



_LOCAL_LIFE_PAGE_HINTS: frozenset[str] = frozenset(_rule_tokens("page_hints"))
_LOCAL_LIFE_CONTEXT_KEYS: frozenset[str] = frozenset(_rule_tokens("context_keys"))
_LOCAL_LIFE_DOMAIN_TOKENS: tuple[str, ...] = get_all_domain_tokens()
_LOCAL_LIFE_TOOL_ACTIONS: frozenset[str] = frozenset(_rule_tokens("tool_actions"))
_LOCAL_LIFE_RAG_ACTIONS: frozenset[str] = frozenset(_rule_tokens("rag_actions"))
_LOCAL_LIFE_MIXED_ACTIONS: frozenset[str] = frozenset(_rule_tokens("mixed_actions"))
_PROFILE_PATTERNS: tuple[str, ...] = _rule_tokens("profile_patterns")
_CONVERSATION_RECAP_PATTERNS: tuple[str, ...] = _rule_tokens("conversation_recap_patterns")
_APPROVE_TOKENS: tuple[str, ...] = _rule_tokens("approve_tokens")
_REJECT_TOKENS: tuple[str, ...] = _rule_tokens("reject_tokens")


@dataclass(frozen=True)
class HeuristicIntentGate:
    """Fast local intent gate used before LLM classification."""

    def fast_decide(self, request: TurnUnderstandingRequest) -> FastDecision | None:
        command = request.command
        persistent = request.persistent
        message = (command.message or "").strip()
        lowered = message.lower()

        if not message:
            return FastDecision(
                intent=IntentType.EXPLAIN,
                needs_rag=False,
                needs_tool=False,
                needs_clarify=True,
                needs_query_rewrite=False,
                confidence=0.0,
                key_slots={"direct_response_kind": "empty"},
                extra={"route_candidate": "empty", "direct_response_kind": "empty"},
            )

        style = _response_mode_to_style(command.response_mode)
        approval_resume = _classify_approval_resume(command, message, lowered, persistent)
        if approval_resume is not None:
            return _turn_result_to_fast_decision(approval_resume)

        local_life = _classify_local_life_turn(command, message, lowered, style or OutputStyle.DETAILED, persistent)
        if local_life is not None:
            return _turn_result_to_fast_decision(local_life)

        return None

    def fallback_decide(self, request: TurnUnderstandingRequest) -> FastDecision:
        command = request.command
        persistent = request.persistent
        message = (command.message or "").strip()
        lowered = message.lower()
        style = _response_mode_to_style(command.response_mode)
        if style is None:
            if any(token in lowered for token in ("compare", "difference", "vs")) or _contains_any(message, _rule_tokens("compare_tokens")):
                style = OutputStyle.COMPARISON
            elif any(token in lowered for token in ("brief", "simple")) or _contains_any(message, ("简单", "简短")):
                style = OutputStyle.BRIEF
            else:
                style = OutputStyle.DETAILED

        if not message:
            return FastDecision(
                intent=IntentType.EXPLAIN,
                needs_rag=False,
                needs_tool=False,
                needs_clarify=True,
                needs_query_rewrite=False,
                confidence=0.0,
                key_slots={"direct_response_kind": "empty"},
                extra={"route_candidate": "empty", "direct_response_kind": "empty"},
            )

        chinese_follow_up = _looks_like_follow_up_query(message, lowered, persistent)
        if _looks_like_profile_query(message, lowered):
            return FastDecision(
                intent=IntentType.EXPLAIN,
                needs_rag=False,
                needs_tool=False,
                needs_clarify=False,
                needs_query_rewrite=False,
                confidence=0.95,
                key_slots={
                    "topic_hint": command.topic_hint,
                    "question_type": "profile",
                    "requested_style": style.value if style else None,
                },
                extra={
                    "route_candidate": "profile",
                    "route_candidates": _route_candidates_metadata(
                        chosen="profile",
                        profile_matched=True,
                        local_life_matched=False,
                        chosen_reason="assistant_capability_question",
                        chosen_decision=TurnDecision.DIRECT_ANSWER,
                        chosen_intent=IntentType.EXPLAIN,
                        direct_response_kind="profile",
                    ),
                    "direct_response_kind": "profile",
                },
            )

        local_life = _classify_local_life_turn(command, message, lowered, style, persistent)
        if local_life is not None:
            return _turn_result_to_fast_decision(local_life)

        intent = IntentType.EXPLAIN
        confidence = 0.72
        if any(token in lowered for token in ("difference", "compare", "vs")) or _contains_any(message, _rule_tokens("compare_tokens")):
            intent = IntentType.COMPARE
            confidence = 0.88
        elif any(token in lowered for token in ("summary", "recap")) or _contains_any(message, _rule_tokens("conversation_recap_patterns")):
            intent = IntentType.SUMMARY
            confidence = 0.82
        elif chinese_follow_up:
            intent = IntentType.FOLLOW_UP
            confidence = 0.58 if persistent.recent_entities else 0.42

        needs_tool = intent in {IntentType.RECOMMEND}
        needs_rag = intent in {
            IntentType.EXPLAIN,
            IntentType.COMPARE,
            IntentType.SUMMARY,
            IntentType.FOLLOW_UP,
            IntentType.RECOMMEND,
        }
        needs_query_rewrite = bool(
            _contains_reference_token(message, lowered)
            or chinese_follow_up
            or intent in {IntentType.COMPARE, IntentType.RECOMMEND}
        )
        return FastDecision(
            intent=intent,
            needs_rag=needs_rag,
            needs_tool=needs_tool,
            needs_clarify=False,
            needs_query_rewrite=needs_query_rewrite,
            confidence=confidence,
            key_slots={
                "topic_hint": command.topic_hint,
                "question_type": intent.value,
                "requested_style": style.value if style else None,
            },
            extra={
                "route_candidate": "knowledge",
                "route_candidates": _route_candidates_metadata(
                    chosen="knowledge",
                    profile_matched=False,
                    local_life_matched=False,
                    chosen_reason=f"default:{intent.value}",
                    chosen_decision=TurnDecision.TOOL_THEN_ANSWER if needs_tool else TurnDecision.RETRIEVE_THEN_ANSWER,
                    chosen_intent=intent,
                ),
            },
        )


class HeuristicModelGateway:
    def __init__(self, gate: HeuristicIntentGate | None = None) -> None:
        self._gate = gate or HeuristicIntentGate()

    def classify_turn(self, request: TurnUnderstandingRequest) -> FastDecision:
        return self._gate.fallback_decide(request)


def _contains_reference_token(message: str, lowered: str) -> bool:
    return any(token in lowered for token in ("this", "that", "previous", "it")) or any(
        token in message for token in ("这家", "那家", "这个", "上一个")
    )


def _looks_like_follow_up_query(message: str, lowered: str, persistent) -> bool:
    if _contains_reference_token(message, lowered):
        return True
    if not (persistent.current_topic or persistent.recent_entities or persistent.last_retrieval_topic):
        return False
    short_follow_up = len(message) <= 14 and any(token in message for token in _rule_tokens("compare_tokens"))
    return short_follow_up


def _looks_like_profile_query(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    if _contains_any(compact, _PROFILE_PATTERNS) or _contains_any(lowered, tuple(pattern.lower() for pattern in _PROFILE_PATTERNS)):
        return True
    if len(compact) <= 12 and any(token in compact for token in ("功能", "工能", "能力")) and any(
        token in compact for token in ("你", "我", "介绍", "帮助", "是什么", "是谁")
    ):
        return True
    return any(token in lowered for token in ("what can you do", "what are your capabilities", "what can you help with"))


def _looks_like_conversation_recap(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    if _contains_any(compact, _CONVERSATION_RECAP_PATTERNS) or _contains_any(lowered, tuple(pattern.lower() for pattern in _CONVERSATION_RECAP_PATTERNS)):
        return True
    return any(token in compact for token in ("记得", "刚才", "上一个问题", "继续刚才", "前面我们")) and any(
        token in compact for token in ("说过", "聊过", "说到", "话题", "内容", "什么")
    )


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _looks_like_greeting(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("greeting_tokens")
    if _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens)):
        return True
    return len(compact) <= 8 and any(token in compact for token in ("你好", "您好", "在吗"))


def _looks_like_thanks(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("thanks_tokens")
    return _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens))


def _looks_like_nearby_recommendation(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("nearby_tokens")
    if _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens)):
        return True
    return any(token in compact for token in ("附近", "周边")) and any(token in compact for token in ("推荐", "找", "看看", "有什么"))


def _looks_like_merchant_detail_query(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("detail_tokens")
    if _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens)):
        return True
    return any(token in compact for token in ("这家", "这个", "那家")) and any(token in compact for token in ("店", "商家", "饭店"))


def _looks_like_compare_query(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("compare_tokens")
    return _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens))


def _looks_like_route_plan_query(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    tokens = _rule_tokens("route_tokens")
    if _contains_any(compact, tokens) or _contains_any(lowered, tuple(token.lower() for token in tokens)):
        return True
    return any(token in compact for token in ("去", "到")) and any(token in compact for token in ("怎么", "路线", "导航", "规划", "计划"))


def _turn_result_to_fast_decision(result) -> FastDecision:
    slots = dict(getattr(result, "slots", {}) or {})
    extra = dict(getattr(result, "extra", {}) or {})
    decision = getattr(result, "decision", TurnDecision.DIRECT_ANSWER)
    local_life_action = str(slots.get("local_life_intent") or extra.get("local_life_intent") or "").strip().lower()
    approval_resume = bool(slots.get("approval_resume") or extra.get("approval_resume"))
    if approval_resume:
        needs_rag = False
        needs_tool = True
    elif local_life_action in {"booking", "coupon"}:
        needs_rag = True
        needs_tool = True
    elif local_life_action in _LOCAL_LIFE_TOOL_ACTIONS:
        needs_rag = False
        needs_tool = True
    elif local_life_action in _LOCAL_LIFE_RAG_ACTIONS:
        needs_rag = True
        needs_tool = False
    elif local_life_action in _LOCAL_LIFE_MIXED_ACTIONS:
        needs_rag = True
        needs_tool = True
    else:
        needs_rag = decision in {TurnDecision.RETRIEVE_THEN_ANSWER, TurnDecision.TOOL_THEN_ANSWER}
        needs_tool = decision == TurnDecision.TOOL_THEN_ANSWER
    needs_clarify = decision == TurnDecision.CLARIFY
    needs_query_rewrite = bool(
        slots.get("needs_query_rewrite")
        or extra.get("needs_query_rewrite")
        or extra.get("rewrite_required")
        or extra.get("rewrite_applied")
    )
    return FastDecision(
        intent=getattr(result, "intent", IntentType.EXPLAIN),
        needs_rag=needs_rag,
        needs_tool=needs_tool,
        needs_clarify=needs_clarify,
        needs_query_rewrite=needs_query_rewrite,
        confidence=float(getattr(result, "intent_confidence", 0.0) or 0.0),
        key_slots=slots,
        extra=extra,
    )


def _context_value(context: dict[str, object], *keys: str):
    for key in keys:
        value = context.get(key)
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _looks_like_local_life_domain(command, message: str, lowered: str, persistent) -> bool:
    context = dict(command.client_context or {})
    page = str(command.page or context.get("page") or "").strip().lower()
    if page in _LOCAL_LIFE_PAGE_HINTS:
        if any(key in context for key in _LOCAL_LIFE_CONTEXT_KEYS):
            return True
        if _contains_any(message, _LOCAL_LIFE_DOMAIN_TOKENS):
            return True

    if any(key in context for key in _LOCAL_LIFE_CONTEXT_KEYS):
        return True
    if _has_local_life_session_anchor(persistent) and (
        _looks_like_local_life_follow_up(message, lowered) or _looks_like_local_life_status_query(message, lowered)
    ):
        return True
    topic_hint = getattr(command, "topic_hint", None)
    if topic_hint and str(topic_hint).strip().lower() not in {"assistant", "ai"}:
        if (
            _contains_any(message, _LOCAL_LIFE_DOMAIN_TOKENS)
            or _looks_like_local_life_follow_up(message, lowered)
            or _looks_like_local_life_status_query(message, lowered)
        ):
            return True
    return _contains_any(message, _LOCAL_LIFE_DOMAIN_TOKENS) or any(
        token in lowered for token in ("restaurant", "coupon", "voucher", "booking", "order", "shop", "merchant")
    )


def _detect_local_life_intent(message: str, lowered: str, has_topic: bool) -> str | None:
    if _looks_like_nearby_recommendation(message, lowered):
        return "recommend"
    if _looks_like_coupon_and_environment_query(message, lowered):
        return "coupon_and_detail"
    if any(token in lowered for token in ("compare", "vs", "difference")) or _contains_any(message, _rule_tokens("compare_tokens")):
        return "compare"
    if has_topic:
        return "detail"
    return None


def _looks_like_coupon_and_environment_query(message: str, lowered: str) -> bool:
    has_coupon = any(token in lowered for token in ("coupon", "voucher", "discount", "deal")) or _contains_any(
        message, _rule_tokens("coupon_tokens")
    )
    has_environment = any(
        token in lowered
        for token in ("environment", "review", "rating", "reputation", "scene", "quiet", "atmosphere", "worth", "fit")
    ) or _contains_any(message, ("怎么样", "评价", "评分", "口碑", "环境", "安静", "氛围", "适合", "家庭聚餐", "带父母", "带长辈", "约会"))
    return has_coupon and has_environment


def _local_life_generic_intent(action: str) -> IntentType:
    if action == "compare":
        return IntentType.COMPARE
    if action == "recommend":
        return IntentType.RECOMMEND
    return IntentType.FOLLOW_UP


def _local_life_turn_decision(action: str) -> TurnDecision:
    if action in _LOCAL_LIFE_MIXED_ACTIONS:
        return TurnDecision.RETRIEVE_THEN_ANSWER
    if action in _LOCAL_LIFE_RAG_ACTIONS:
        return TurnDecision.RETRIEVE_THEN_ANSWER
    return TurnDecision.TOOL_THEN_ANSWER


def _response_mode_to_style(response_mode: object) -> OutputStyle | None:
    if isinstance(response_mode, OutputStyle):
        return response_mode
    if response_mode in (None, ""):
        return None
    try:
        return OutputStyle(str(response_mode))
    except Exception:
        return None


def _build_local_life_slots(command, message: str, action: str, style: OutputStyle | None, persistent=None) -> dict[str, object]:
    context = dict(command.client_context or {})
    location = _context_value(context, "location")
    shop_name = _context_value(context, "shopName", "shop_name") or getattr(command, "topic_hint", None)
    if not shop_name and persistent is not None:
        shop_name = getattr(persistent, "selected_shop_name", None) or getattr(persistent, "current_topic", None)
    category = _context_value(context, "typeName", "type_name", "category")
    if not category and persistent is not None:
        current_constraints = getattr(persistent, "current_constraints", {}) or {}
        if isinstance(current_constraints, dict):
            category = current_constraints.get("category")
    slots: dict[str, object] = {
        "domain": "local_life",
        "local_life_intent": action,
        "question_type": action,
        "topic_hint": getattr(command, "topic_hint", None),
        "query": message,
        "requested_style": style.value if style else None,
    }
    if shop_name not in (None, ""):
        slots["shop_name"] = shop_name
    if category not in (None, ""):
        slots["category"] = category
    if location not in (None, "", [], {}, ()):
        slots["location"] = location
    city = _context_value(context, "city")
    if city in (None, "") and persistent is not None:
        city = getattr(persistent, "current_city", None)
    if city not in (None, ""):
        slots["city"] = city
    shop_id = _context_value(context, "shopId", "shop_id", "selected_shop_id")
    if shop_id in (None, "") and persistent is not None:
        shop_id = getattr(persistent, "selected_shop_id", None)
    if shop_id not in (None, ""):
        slots["shop_id"] = shop_id
    if location in (None, "", [], {}, ()) and persistent is not None:
        location = getattr(persistent, "current_location", {}) or {}
    if location not in (None, "", [], {}, ()):
        slots["location"] = location
    inferred_scene, inferred_preferences = _infer_local_life_scene_preferences(message, slots)
    if inferred_scene and "scene" not in slots:
        slots["scene"] = inferred_scene
    if inferred_preferences:
        raw_prefs = slots.get("preferences")
        base_prefs = list(raw_prefs) if isinstance(raw_prefs, (list, tuple, set)) else []
        merged_preferences = list(dict.fromkeys([*base_prefs, *inferred_preferences]))
        if merged_preferences:
            slots["preferences"] = merged_preferences
    if persistent is not None:
        if getattr(persistent, "current_scene", None):
            slots.setdefault("scene", persistent.current_scene)
        if getattr(persistent, "local_life_preferences", None):
            slots.setdefault("preferences", list(persistent.local_life_preferences))
        if getattr(persistent, "local_life_avoid", None):
            slots.setdefault("avoid", list(persistent.local_life_avoid))
        candidate = _pick_follow_up_candidate(message, getattr(persistent, "last_candidates", []) or [])
        if candidate:
            if candidate.get("id") not in (None, ""):
                slots["shop_id"] = candidate.get("id")
            if candidate.get("name") not in (None, ""):
                slots["shop_name"] = candidate.get("name")
    return slots


def _classify_local_life_turn(command, message: str, lowered: str, style: OutputStyle | None, persistent) -> TurnUnderstandingResult | None:
    if not _looks_like_local_life_domain(command, message, lowered, persistent):
        return None
    has_topic = bool(
        getattr(command, "topic_hint", None)
        or getattr(persistent, "current_topic", None)
        or getattr(persistent, "selected_shop_id", None)
        or getattr(persistent, "last_candidates", None)
    )
    action = _detect_local_life_intent(message, lowered, has_topic)
    if action is None and _pick_follow_up_candidate(message, getattr(persistent, "last_candidates", []) or []):
        action = "detail"
    if action is None:
        return None
    decision = _local_life_turn_decision(action)
    result = TurnUnderstandingResult(
        decision=decision,
        intent=_local_life_generic_intent(action),
        intent_confidence=0.9 if action in {"recommend", "compare", "coupon", "coupon_and_detail", "navigation", "booking", "order_status"} else 0.82,
        requested_output_style=style,
        slots=_build_local_life_slots(command, message, action, style, persistent),
    )
    return result.model_copy(
        update={
            "extra": {
                "route_candidate": "local_life",
                "route_candidates": _route_candidates_metadata(
                    chosen="local_life",
                    profile_matched=_looks_like_profile_query(message, lowered),
                    local_life_matched=True,
                    chosen_reason=f"intent:{result.intent.value}",
                    chosen_decision=decision,
                    chosen_intent=result.intent,
                ),
            }
        }
    )


def _classify_approval_resume(command, message: str, lowered: str, persistent) -> TurnUnderstandingResult | None:
    extra = dict(getattr(persistent, "extra", {}) or {})
    approval_request = extra.get("pending_approval_request")
    if not isinstance(approval_request, dict) or not approval_request:
        return None

    decision = None
    if any(token in message for token in _APPROVE_TOKENS) or any(token in lowered for token in ("approve", "confirm", "continue")):
        decision = "approved"
    elif any(token in message for token in _REJECT_TOKENS) or any(token in lowered for token in ("reject", "deny", "cancel")):
        decision = "rejected"
    if decision is None:
        return None

    style = _response_mode_to_style(command.response_mode)
    slots = _build_local_life_slots(command, message, approval_request.get("tool_name") or "booking", style, persistent)
    slots["tool_name"] = approval_request.get("tool_name")
    slots["tool_input"] = dict(approval_request.get("tool_input") or approval_request.get("input_payload") or {})
    slots["approval_status"] = decision
    slots["approval_request"] = dict(approval_request)
    slots["approval_decision"] = decision
    slots["approval_resume"] = True
    slots["requires_approval"] = False
    return TurnUnderstandingResult(
        decision=TurnDecision.TOOL_THEN_ANSWER,
        intent=IntentType.FOLLOW_UP,
        intent_confidence=0.96,
        requested_output_style=style,
        slots=slots,
    )


def _pick_follow_up_candidate(message: str, candidates) -> dict[str, object] | None:
    if not isinstance(candidates, list) or not candidates:
        return None
    ordinal_map = {
        "第一家": 0,
        "第1家": 0,
        "第一个": 0,
        "第二家": 1,
        "第2家": 1,
        "第二个": 1,
        "第三家": 2,
        "第3家": 2,
        "第三个": 2,
    }
    for token, index in ordinal_map.items():
        if token in message and 0 <= index < len(candidates):
            candidate = candidates[index]
            return dict(candidate) if isinstance(candidate, dict) else None
    return None


def _infer_local_life_scene_preferences(message: str, slots: dict[str, object]) -> tuple[str | None, list[str]]:
    scene = slots.get("scene") if isinstance(slots.get("scene"), str) else None
    raw_preferences = slots.get("preferences")
    preferences = list(raw_preferences) if isinstance(raw_preferences, (list, tuple, set)) else []
    return scene, preferences


def _looks_like_local_life_follow_up(message: str, lowered: str) -> bool:
    compact = message.replace(" ", "")
    if any(token in compact for token in ("第二家", "第二个", "第一家", "第一个", "第三家", "第三个")):
        return True
    return any(token in compact for token in ("怎么样", "哪家", "这家", "那家", "对比", "比较", "详情", "评分", "口碑", "适合")) or any(
        token in lowered for token in ("detail", "review", "rating", "worth", "compare", "difference", "vs")
    )


def _looks_like_local_life_status_query(message: str, lowered: str) -> bool:
    return False


def _has_local_life_session_anchor(persistent) -> bool:
    return any(
        value not in (None, "", [], {}, ())
        for value in (
            getattr(persistent, "current_topic", None) if persistent is not None else None,
            getattr(persistent, "selected_shop_id", None) if persistent is not None else None,
            getattr(persistent, "selected_shop_name", None) if persistent is not None else None,
            getattr(persistent, "current_scene", None) if persistent is not None else None,
            getattr(persistent, "last_candidates", None) if persistent is not None else None,
        )
    )


def _route_candidates_metadata(
    *,
    chosen: str,
    profile_matched: bool,
    local_life_matched: bool,
    chosen_reason: str,
    chosen_decision: TurnDecision,
    chosen_intent: IntentType,
    direct_response_kind: str | None = None,
) -> list[dict[str, object]]:
    return [
        {
            "name": "profile",
            "priority": 0,
            "matched": profile_matched,
            "reason": "assistant_capability_question" if profile_matched else "not_matched",
            "decision": TurnDecision.DIRECT_ANSWER.value,
            "intent": IntentType.EXPLAIN.value,
            "direct_response_kind": "profile" if profile_matched else None,
        },
        {
            "name": "local_life",
            "priority": 10,
            "matched": local_life_matched,
            "reason": "local_life_context" if local_life_matched else "not_matched",
            "decision": chosen_decision.value if local_life_matched else TurnDecision.TOOL_THEN_ANSWER.value,
            "intent": IntentType.RECOMMEND.value,
        },
        {
            "name": "knowledge",
            "priority": 20,
            "matched": chosen == "knowledge",
            "reason": chosen_reason if chosen == "knowledge" else "not_matched",
            "decision": chosen_decision.value,
            "intent": chosen_intent.value,
            "direct_response_kind": direct_response_kind,
        },
    ]
