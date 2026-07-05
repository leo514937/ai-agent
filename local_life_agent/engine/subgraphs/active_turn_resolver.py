"""active_turn_resolver — pending clarification active-turn routing.

This module implements the "Active State First" pattern:

  Layer 1: Deterministic rules (digits, ordinals, exact name, cancel)
  Layer 2: Lightweight fuzzy matching (normalized text, branch/short name)
  Layer 3: Optional bounded LLM interpreter (disabled by default)
  Layer 4: Unified validator → canonical ActiveTurnResult

Every path ends in a validated ``ActiveTurnResult`` that the intake guard
router uses to decide the next LangGraph node.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ... import config
from ...domain.schemas import ActiveTurnResult
from ...domain.graph_state import GraphState
from ...observability.file_logger import get_python_service_logger, log_kv
from ...semantic.slot_extractor import extract_slots
from .._compat import _run_step

_LOGGER = get_python_service_logger()

# ---------------------------------------------------------------------------
# Cancel / abort keywords
# ---------------------------------------------------------------------------

_CANCEL_TERMS: frozenset[str] = frozenset({
    "取消", "算了", "不用了", "不查了", "别查了",
    "重新来", "先不看了", "放弃", "不选了",
})

# ---------------------------------------------------------------------------
# Normalised candidate prefixes to strip during matching
# ---------------------------------------------------------------------------

_WEAK_WORDS_PATTERN = re.compile(
    r"[的那家那个店吧就看刚才帮我想我选你查查帮我看我选|就这]+"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _pending_candidates(pending: Any) -> list[dict[str, Any]]:
    """Extract candidate list from a pending-clarification payload."""
    if pending is None:
        return []
    data = _as_dict(pending)
    return [
        {"shop_id": str(c.get("shop_id", "")), "shop_name": str(c.get("shop_name", "")),
         "address": str(c.get("address", "")), "alias": str(c.get("alias", ""))}
        for c in (data.get("candidate_targets", []) or [])
        if str(c.get("shop_id", "") or "").strip() and str(c.get("shop_name", "") or "").strip()
    ]


def _pending_expired(pending: Any) -> bool:
    """Check whether a pending clarification has expired."""
    data = _as_dict(pending)
    expires_at = data.get("expires_at")
    if expires_at is None:
        created_at = data.get("created_at")
        if created_at is None:
            return False
        try:
            expires_at = created_at + timedelta(seconds=config.CLARIFICATION_TTL_SECONDS)
        except Exception:
            return False
    now = datetime.now(timezone.utc)
    if hasattr(expires_at, "tzinfo") and getattr(expires_at, "tzinfo", None) is not None:
        expiry = expires_at.astimezone(timezone.utc)
    elif hasattr(expires_at, "replace"):
        expiry = expires_at.replace(tzinfo=timezone.utc)
    else:
        return False
    return now >= expiry


# ---------------------------------------------------------------------------
# Layer 1: Deterministic Rules
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Light normalisation: strip whitespace, fullwidth→halfwidth digits."""
    t = (text or "").strip()
    # Fullwidth digit → halfwidth
    t = t.replace("０", "0").replace("１", "1").replace("２", "2").replace("３", "3")\
         .replace("４", "4").replace("５", "5").replace("６", "6").replace("７", "7")\
         .replace("８", "8").replace("９", "9")
    return t


_CHINESE_ORDINAL_MAP: dict[str, int] = {
    "第一个": 1, "第一家": 1, "第一": 1,
    "第1个": 1, "第1家": 1,
    "第二个": 2, "第二家": 2, "第二": 2,
    "第2个": 2, "第2家": 2,
    "第三个": 3, "第三家": 3, "第三": 3,
    "第3个": 3, "第3家": 3,
    "第四个": 4, "第四家": 4, "第四": 4,
    "第4个": 4, "第4家": 4,
}

_CANDIDATE_POINTERS: frozenset[str] = frozenset({
    "就这个", "这个", "这家", "选这个", "选这家",
    "选第一个", "选第二个", "选第三个",
    "刚才第一个", "刚才第二个", "刚才第三个",
})


def _rule_recognizer(text: str, pending: Any) -> ActiveTurnResult | None:
    """Layer 1: deterministic rules for digits, ordinals, cancel, exact match.

    Returns an ``ActiveTurnResult`` when a rule fires, or ``None`` to
    fall through to fuzzy matching.
    """
    compact = _normalize_text(text)
    if not compact:
        return None

    candidates = _pending_candidates(pending)
    candidate_count = len(candidates)

    # -- Cancel / abort --
    if compact in _CANCEL_TERMS or any(term in compact for term in ("取消", "算了", "不用了")):
        return ActiveTurnResult(
            route="pending_cancelled", source="rule", reason="user_cancelled",
            confidence=1.0,
        )

    # -- Pure digit --
    if compact.isdigit():
        num = int(compact)
        if 1 <= num <= candidate_count if candidate_count > 0 else False:
            return ActiveTurnResult(
                route="pending_restored", source="rule",
                selected_index=num, selected_candidate=candidates[num - 1],
                confidence=1.0, reason=f"digit_selection_{num}",
            )
        else:
            return ActiveTurnResult(
                route="pending_out_of_range", source="rule",
                selected_index=num,
                confidence=1.0, reason=f"digit_{num}_out_of_range_max_{candidate_count}",
            )

    # -- Chinese ordinal --
    for key, value in _CHINESE_ORDINAL_MAP.items():
        if key in compact:
            if 1 <= value <= candidate_count:
                return ActiveTurnResult(
                    route="pending_restored", source="rule",
                    selected_index=value, selected_candidate=candidates[value - 1],
                    confidence=1.0, reason=f"ordinal_{key}",
                )
            else:
                return ActiveTurnResult(
                    route="pending_out_of_range", source="rule",
                    selected_index=value,
                    confidence=1.0, reason=f"ordinal_{key}_out_of_range",
                )

    # -- Candidate pointers (deictic) --
    if compact in _CANDIDATE_POINTERS:
        # "就这个" / "这个" with no additional context → ambiguous, not restored
        # But if there's exactly 1 candidate, that's clear
        if candidate_count == 1:
            return ActiveTurnResult(
                route="pending_restored", source="rule",
                selected_index=1, selected_candidate=candidates[0],
                confidence=0.9, reason="deictic_single_candidate",
            )
        return None  # let fuzzy or LLM handle

    # -- Exact candidate name match --
    for idx, cand in enumerate(candidates, start=1):
        shop_name = cand.get("shop_name", "").strip()
        if shop_name and shop_name == compact:
            return ActiveTurnResult(
                route="pending_restored", source="rule",
                selected_index=idx, selected_candidate=cand,
                confidence=1.0, reason="exact_name_match",
            )

    return None  # fall through


# ---------------------------------------------------------------------------
# Layer 2: Lightweight Fuzzy Matching
# ---------------------------------------------------------------------------


def _strip_weak_words(text: str) -> str:
    """Remove weak / filler tokens like '那家', '这个', '吧', '帮我看'."""
    return _WEAK_WORDS_PATTERN.sub("", text).strip()


def _semantic_reply_frame(text: str) -> dict[str, Any]:
    try:
        frame = extract_slots(text, "local_life")
    except Exception:
        return {}
    if hasattr(frame, "model_dump"):
        dumped = frame.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return frame if isinstance(frame, dict) else {}


def _extract_short_names(shop_name: str) -> list[str]:
    """Extract short-name variants from a candidate shop name.

    Examples:
      "海底捞(牡丹园店)" → ["海底捞", "牡丹园店", "牡丹园"]
      "川味轩(知春路店)" → ["川味轩", "知春路店", "知春路"]
      "山城一锅" → ["山城一锅"]
    """
    variants: list[str] = [shop_name]
    # Remove parenthetical branch info
    base = re.sub(r"[（(][^）)]*[）)]", "", shop_name).strip()
    if base and base != shop_name:
        variants.append(base)
    # Extract branch name from parentheses
    m = re.search(r"[（(]([^）)]+)[）)]", shop_name)
    if m:
        branch = m.group(1).strip()
        if branch:
            variants.append(branch)
            # Remove "店" suffix from branch
            branch_short = re.sub(r"店$", "", branch).strip()
            if branch_short and branch_short != branch:
                variants.append(branch_short)
    return variants


def _fuzzy_recognizer(text: str, pending: Any) -> ActiveTurnResult | None:
    """Layer 2: light-weight fuzzy matching against candidate names.

    Normalises the user input and each candidate's display name, then tries
    exact-normalised match → substring match → token overlap → branch keyword.
    """
    compact = _normalize_text(text).strip()
    if not compact:
        return None

    candidates = _pending_candidates(pending)
    if not candidates:
        return None

    # Normalise user input: strip weak words, lowercase
    user_clean = _strip_weak_words(compact).lower()

    matched_indices: list[int] = []

    for idx, cand in enumerate(candidates, start=1):
        shop_name = (cand.get("shop_name") or "").strip()
        address = (cand.get("address") or "").strip()
        alias = (cand.get("alias") or "").strip()

        # Collect all variants
        variants = _extract_short_names(shop_name)
        if address and address not in variants:
            variants.append(address)
        if alias and alias not in variants:
            variants.append(alias)

        normalised_variants = [v.lower().strip() for v in variants if v.strip()]

        # a) Exact normalised match
        if any(user_clean == v for v in normalised_variants):
            matched_indices.append(idx)
            continue

        # b) Substring match (user text is fully contained in a variant)
        if any(user_clean in v for v in normalised_variants):
            matched_indices.append(idx)
            continue

        # c) Variant contains user text
        if any(v in user_clean for v in normalised_variants if len(v) >= 2):
            matched_indices.append(idx)
            continue

        # d) Token overlap (for longer user input)
        user_tokens = set(t for t in re.split(r"[\s,，、/]+", user_clean) if len(t) >= 2)
        if user_tokens:
            for v in normalised_variants:
                v_tokens = set(t for t in re.split(r"[\s,，、/]+", v) if len(t) >= 2)
                if user_tokens & v_tokens:
                    matched_indices.append(idx)
                    break

    if len(matched_indices) == 1:
        idx = matched_indices[0]
        return ActiveTurnResult(
            route="pending_restored", source="fuzzy",
            selected_index=idx, selected_candidate=candidates[idx - 1],
            confidence=0.85, reason="fuzzy_name_match",
        )

    if len(matched_indices) > 1:
        return ActiveTurnResult(
            route="pending_invalid", source="fuzzy",
            reason=f"multiple_candidates_matched_{matched_indices}",
            confidence=0.3,
        )

    return None  # fall through


# ---------------------------------------------------------------------------
# Layer 3: Optional Bounded LLM Pending Interpreter
# ---------------------------------------------------------------------------

# Feature flag: bounded LLM pending interpreter is OFF by default
_ENABLE_BOUNDED_PENDING_LLM: bool = False


def _bounded_llm_recognizer(text: str, pending: Any) -> ActiveTurnResult | None:
    """Layer 3: bounded LLM pending interpreter (disabled by default).

    Only called when all rules and fuzzy matching fail. The LLM receives
    a scoped prompt with the pending candidates and must return a controlled
    JSON decision.
    """
    if not _ENABLE_BOUNDED_PENDING_LLM:
        return None

    candidates = _pending_candidates(pending)
    pending_data = _as_dict(pending)

    # Build a safe, scoped prompt
    candidate_summary = "\n".join(
        f"{i}. {c['shop_name']}" + (f" ({c['address']})" if c.get('address') else "")
        for i, c in enumerate(candidates, start=1)
    )

    prompt = (
        f"用户当前需要回复一个系统询问。\n"
        f"系统询问：{pending_data.get('reason', '请选择一家店')}\n"
        f"候选选项：\n{candidate_summary}\n"
        f"用户输入：{text}\n\n"
        f"请判断用户的意图，输出 JSON：\n"
        f'{{"decision": "select_candidate|invalid|out_of_range|cancel|topic_switch|unclear", '
        f'"selected_index": <1-based int or null>, '
        f'"confidence": 0.0-1.0, '
        f'"new_query": "<如果decision=topic_switch，提取用户的新query>"}}'
    )

    # Note: actual LLM call is placeholder - depends on project LLM backend
    # When enabled, call project's LLM with the prompt and parse JSON response

    return None  # Placeholder: not implemented until feature flag enabled


# ---------------------------------------------------------------------------
# Layer 4: Unified Validator
# ---------------------------------------------------------------------------


def _validate_active_turn_result(
    raw_result: ActiveTurnResult,
    pending: Any,
) -> ActiveTurnResult:
    """Unified validator: ensure the result is consistent with pending state.

    This runs on every path (rule / fuzzy / LLM) and enforces:
      - selected_index is 1-based and within candidate range
      - selected_candidate is populated when route=pending_restored
      - expired pending cannot be restored
      - confidence threshold check
    """
    candidates = _pending_candidates(pending)
    candidate_count = len(candidates)

    # Expiry check always wins
    if _pending_expired(pending):
        return ActiveTurnResult(
            route="pending_expired", source="validator",
            reason="pending_expired_during_validation",
            confidence=1.0,
        )

    route = raw_result.route

    # pending_restored: must have valid index and candidate
    if route == "pending_restored":
        idx = raw_result.selected_index
        if idx is None or not (1 <= idx <= candidate_count):
            return ActiveTurnResult(
                route="pending_invalid", source="validator",
                reason=f"restore_with_invalid_index_{idx}",
                confidence=0.0,
            )
        if raw_result.selected_candidate is None:
            return ActiveTurnResult(
                route="pending_restored", source=raw_result.source,
                selected_index=idx, selected_candidate=candidates[idx - 1],
                confidence=raw_result.confidence, reason=raw_result.reason,
            )

    # pending_out_of_range: index must be out of range
    if route == "pending_out_of_range":
        if raw_result.selected_index is not None and candidate_count > 0:
            if 1 <= raw_result.selected_index <= candidate_count:
                return ActiveTurnResult(
                    route="pending_restored", source="validator",
                    selected_index=raw_result.selected_index,
                    selected_candidate=candidates[raw_result.selected_index - 1],
                    confidence=0.8, reason="validator_corrected_oob_to_restore",
                )

    # topic_switch: must have new_query
    if route == "topic_switch":
        if not raw_result.new_query:
            return ActiveTurnResult(
                route="pending_invalid", source="validator",
                reason="topic_switch_without_new_query",
                confidence=0.0,
            )

    # Confidence floor: below 0.5 → invalid
    if route in ("pending_restored", "topic_switch") and raw_result.confidence < 0.5:
        return ActiveTurnResult(
            route="pending_invalid", source="validator",
            reason=f"low_confidence_{raw_result.confidence}",
            confidence=raw_result.confidence,
        )

    return raw_result


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


def resolve_active_turn(
    text: str,
    pending: Any,
) -> ActiveTurnResult:
    """Resolve the user's turn in the context of an active pending clarification.

    Applies the four-layer pipeline:
      1. Deterministic rules
      2. Fuzzy matching
      3. Bounded LLM (optional, feature-gated)
      4. Unified validator

    Args:
        text: The user's input text (raw or normalized).
        pending: The ``PendingClarification`` object (dict or model).

    Returns:
        A validated ``ActiveTurnResult``.
    """
    # No pending → normal query
    if pending is None:
        return ActiveTurnResult(route="normal_query", source="none", confidence=1.0)

    # Expiry check first
    if _pending_expired(pending):
        return ActiveTurnResult(
            route="pending_expired", source="rule",
            reason="pending_expired", confidence=1.0,
        )

    reply_frame = _semantic_reply_frame(text)
    if reply_frame.get("new_task_override"):
        result = ActiveTurnResult(
            route="topic_switch", source="semantic",
            new_query=text, reason="semantic_new_task_override",
            confidence=min(float(reply_frame.get("confidence", 0.7) or 0.7), 0.9),
        )
        return _validate_active_turn_result(result, pending)
    if reply_frame.get("constraint_update"):
        result = ActiveTurnResult(
            route="topic_switch", source="semantic",
            new_query=text, reason="semantic_constraint_update",
            confidence=min(float(reply_frame.get("confidence", 0.7) or 0.7), 0.85),
        )
        return _validate_active_turn_result(result, pending)

    # Layer 1: Rules
    result = _rule_recognizer(text, pending)
    if result is not None:
        return _validate_active_turn_result(result, pending)

    # Layer 2: Fuzzy
    result = _fuzzy_recognizer(text, pending)
    if result is not None:
        return _validate_active_turn_result(result, pending)

    # Layer 3: Bounded LLM (optional)
    result = _bounded_llm_recognizer(text, pending)
    if result is not None:
        return _validate_active_turn_result(result, pending)

    # Fallback: no match → invalid
    result = ActiveTurnResult(
        route="pending_invalid", source="none",
        reason="no_rule_fuzzy_or_llm_match",
        confidence=0.0,
    )
    return _validate_active_turn_result(result, pending)


# ---------------------------------------------------------------------------
# Topic-switch heuristic (used outside pending scope as well)
# ---------------------------------------------------------------------------


_TOPIC_SWITCH_HINTS = (
    "算了", "换一家", "换个", "重新", "重新推荐",
    "讲个笑话", "笑话", "别查了", "不查了",
)


def _should_treat_as_topic_switch(text: str, pending: Any = None, reply_frame: dict[str, Any] | None = None) -> bool:
    """Heuristic: does the input look like a new standalone query?"""
    compact = (text or "").strip()
    if not compact:
        return False
    pending_data = _as_dict(pending)
    pending_slot = str(pending_data.get("missing_slot_type", "") or "").strip()
    reply = _as_dict(reply_frame)
    if pending_slot in {
        "missing_location",
        "missing_shop",
        "missing_shop_target",
        "missing_comparison_targets",
        "missing_exploration_location",
        "missing_category",
        "ambiguous_shop",
        "ambiguous_comparison_targets",
        "unresolved_deictic_reference",
        "unresolved_ordinal_reference",
    }:
        if any(
            reply.get(key)
            for key in (
                "location_reference",
                "location",
                "shop_reference",
                "shop_target",
                "ordinal_reference",
                "deictic_reference",
                "comparison_targets",
                "merchant_mentions",
                "preferences",
                "soft_preferences",
                "hard_constraints",
                "ranking_signals",
                "category",
            )
        ):
            return False
        if pending_slot in {"missing_location", "missing_exploration_location"} and any(token in compact for token in ("附近", "周边", "商圈", "北邮", "北京邮电大学")):
            return False
        if pending_slot in {"missing_shop", "missing_shop_target", "ambiguous_shop", "unresolved_deictic_reference", "unresolved_ordinal_reference"} and any(
            token in compact for token in ("这家", "那家", "第一家", "第二家", "第三家", "第一个", "第二个", "第三个")
        ):
            return False
        if pending_slot == "missing_comparison_targets" and any(token in compact for token in ("第一家", "第二家", "第三家", "这家", "这三家", "这几家")):
            return False
    if any(hint in compact for hint in _TOPIC_SWITCH_HINTS):
        return True
    # 4+ chars with domain keywords → likely new topic
    if len(compact) >= 4:
        keywords = ("附近", "火锅", "推荐", "优惠券", "有券",
                     "营业", "哪家", "怎么样", "好吃", "评价",
                     "距离", "多远", "怎么去", "怎么走", "开门")
        if any(kw in compact for kw in keywords):
            return True
    return False


# ---------------------------------------------------------------------------
# LangGraph handler
# ---------------------------------------------------------------------------


def _h_active_turn_resolver(state: GraphState) -> dict:
    """LangGraph step handler: resolve active pending clarification.

    Must be called AFTER ``_h_load_session`` so ``session_state_before``
    is populated, and BEFORE ``_h_top_intent_router``.

    Reads:
      - ``raw_text`` or ``normalized_text``
      - ``session_state_before.pending_clarification``
    Writes:
      - ``active_turn_result`` (dict)
      - event_log entry
    """
    session_before = state.get("session_state_before") or state.get("session_state")
    pending = None
    if session_before is not None:
        pending = (
            getattr(session_before, "pending_clarification", None)
            if not isinstance(session_before, dict)
            else session_before.get("pending_clarification")
        )

    text = state.get("raw_text", "") or state.get("normalized_text", "") or ""
    reply_frame = _semantic_reply_frame(text)

    result = resolve_active_turn(text, pending)

    # If the resolver produced pending_invalid, check topic-switch heuristic
    # as a final pass before giving up.
    if result.route == "pending_invalid" and _should_treat_as_topic_switch(text, pending=pending, reply_frame=reply_frame):
        result = ActiveTurnResult(
            route="topic_switch", source="rule",
            new_query=text, reason="topic_switch_heuristic",
            confidence=0.6,
        )

    result_dict = result.model_dump() if hasattr(result, "model_dump") else _as_dict(result)

    log_kv(
        _LOGGER, logging.INFO, "[ACTIVE_TURN_RESOLVER]",
        tone="route",
        route=result.route,
        source=result.source,
        reason=result.reason,
        selected_index=result.selected_index,
        confidence=result.confidence,
    )

    from .._compat import _log
    return {
        "active_turn_result": result_dict,
        **_log(state, "active_turn_resolver",
              route=result.route, source=result.source,
              reason=result.reason, confidence=result.confidence),
    }


def h_active_turn_resolver_outer(state: GraphState) -> dict:
    """Outer wrapper for ``active_turn_resolver`` graph node.

    Calls the multi-layer resolver and sets ``active_turn_route`` for
    the downstream conditional edge.
    """
    from .._compat import _state_delta

    before = dict(state)
    log_kv(_LOGGER, logging.INFO, "[SUBGRAPH_ENTER]", tone="route",
           subgraph="active_turn_resolver", trace_id=state.get("trace_id", ""),
           raw_text=state.get("raw_text", ""))
    working = state  # _h_active_turn_resolver reads directly from state
    working = _run_step(working, _h_active_turn_resolver)
    active_result = working.get("active_turn_result") or {}
    atr_route = str(active_result.get("route", "") or "normal_query")

    after = {
        **working,
        "active_turn_route": atr_route,
    }
    log_kv(_LOGGER, logging.INFO, "[ROUTE_DECISION]", tone="route",
           subgraph="active_turn_resolver", route=atr_route,
           source=active_result.get("source"),
           reason=active_result.get("reason"))
    return _state_delta(before, after, always_include={"active_turn_route", "active_turn_result"})
