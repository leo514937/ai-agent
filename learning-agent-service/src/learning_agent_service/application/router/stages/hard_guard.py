from __future__ import annotations

import re
from typing import Any, Mapping

from ....domain.contracts import PersistentSessionContext
from ...routing_primitives import (
    _client_context_has_anchor,
    _client_context_has_candidate_anchor,
    _contains_any,
    _context_has_anchor,
    _context_has_candidate_anchor,
    _detect_response_kind,
    build_input_quality,
    normalize_query,
)
from .types import HardGuardResult

_PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_NOISE_REPEAT_RE = re.compile(r"^(.)\1{5,}$", re.UNICODE)
_LOW_INFO_TOKENS = {
    "嗯", "啊", "哦", "唔", "好", "然后", "还有", "那", "这个", "那个",
    "就是", "对", "行", "可以", "额", "呃", "嗯嗯",
}
_REFERENCE_TOKENS = (
    "这个呢", "那家呢", "第二个呢", "第二家呢", "第一个呢",
    "它呢", "这家", "那家", "这个店", "那个店", "这个套餐", "那个套餐",
    "第二个", "第二家", "第一个", "前一个", "后一个",
)

def check_hard_guard(
    raw_query: str,
    persistent: PersistentSessionContext,
    client_context: Mapping[str, Any] | None = None,
) -> HardGuardResult:
    normalized = normalize_query(raw_query)
    if not normalized or normalized.strip() == "":
        return HardGuardResult(blocked=True, reason="empty_input", required_action="reject", route_candidate="reject")

    if _PUNCT_ONLY_RE.fullmatch(normalized):
        return HardGuardResult(blocked=True, reason="pure_punctuation", required_action="reject", route_candidate="reject")

    compact = normalized.replace(" ", "")
    if len(compact) >= 6 and len(set(compact)) <= 2:
        return HardGuardResult(blocked=True, reason="repeated_noise", required_action="reject", route_candidate="reject")

    input_quality = build_input_quality(raw_query)
    response_kind, _ = _detect_response_kind(raw_query)

    # 1. Low Information
    if input_quality.kind == "low_information":
        if response_kind in {"greeting", "thanks", "profile"}:
            return HardGuardResult(blocked=False)
        
        has_anchor = _context_has_anchor(persistent) or _client_context_has_anchor(client_context)
        if has_anchor and _contains_any(normalized, ("然后", "还有", "那", "继续")):
            return HardGuardResult(blocked=False)
            
        return HardGuardResult(blocked=True, reason="low_information", required_action="clarify", route_candidate="clarify")

    # 2. Ambiguous Reference
    if input_quality.kind == "ambiguous_reference":
        has_anchor = (
            _context_has_candidate_anchor(persistent)
            or _context_has_anchor(persistent)
            or _client_context_has_candidate_anchor(client_context)
            or _client_context_has_anchor(client_context)
        )
        if not has_anchor:
            return HardGuardResult(blocked=True, reason="ambiguous_reference_without_context", required_action="clarify", route_candidate="clarify")

    # 3. Incomplete Recommendation
    if input_quality.kind == "incomplete_recommendation":
        # 推荐类请求即使缺少城市/位置，也应继续进入推荐流，由后续节点决定是部分回答还是补充上下文。
        # 这里不再提前打成澄清，避免“附近/最近”类查询被硬拦截。
        pass

    return HardGuardResult(blocked=False)
