from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_contract import AnswerContract
from .claim_grounding import (
    build_claim_bindings,
    is_high_risk_answer_context,
    summarize_claim_bindings,
    _HYBRID_CLAIMS,
    _RAG_REQUIRED_CLAIMS,
    _TOOL_REQUIRED_CLAIMS,
)
from .grounding_policy import claim_policy_for_facet

_FACET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coupon": ("券", "优惠", "代金券", "团购", "折扣", "打折"),
    "open_status": ("营业", "开门", "开业", "营业时间", "关门"),
    "distance_eta": ("离我多远", "距离", "有多远", "公里", "路程", "怎么走", "怎么去", "导航"),
    "price": ("人均", "预算", "价格", "元"),
    "scene_fit": ("适合", "约会", "家庭", "长辈", "带娃", "安静", "停车"),
    "environment": ("环境", "氛围", "安静", "吵", "包间"),
    "taste": ("口味", "味道", "好吃", "菜"),
    "service": ("服务", "态度", "排队"),
    "recommendation": ("推荐", "优先推荐", "这几家", "几家"),
}
_DYNAMIC_REaltime_TOKENS = ("实时", "现在", "刚查", "最新", "当前")
_STRICT_BRANCHES = {"strict_template", "strict_natural"}
_STRICT_GENERIC_TOKENS = {
    "这家",
    "这家店",
    "这边",
    "这里",
    "当前",
    "目前",
    "现在",
    "暂时",
    "可以",
    "如果",
    "建议",
    "综合建议",
    "总体来说",
    "整体来说",
    "大致",
    "大概",
    "左右",
    "适合",
    "信息",
    "情况",
    "结果",
    "方面",
    "继续",
    "确认",
    "再确认",
    "再看",
    "先看",
    "先",
    "还有",
    "而且",
    "不过",
    "然后",
    "因此",
    "同时",
    "另外",
    "主要",
    "基本",
    "一般",
    "不错",
    "很好",
    "比较",
    "可能",
    "足够",
    "需要",
    "告诉",
    "说明",
    "推荐",
}
_SHOP_LIKE_PATTERN = re.compile(r"([A-Za-z0-9\u4e00-\u9fff·（）()]{2,20}(?:店|餐厅|饭店|门店|商家))")
_NUMERIC_PATTERN = re.compile(r"\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+")


class AnswerLintResult(BaseModel):
    passed: bool = True
    severity: Literal["pass", "warn", "block"] = "pass"
    issues: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    cross_shop_leak: bool = False
    unsupported_realtime_claim: bool = False
    unsolicited_recommendation: bool = False
    claim_bindings: list[dict[str, Any]] = Field(default_factory=list)
    claim_count: int = 0
    supported_claim_count: int = 0
    partial_claim_count: int = 0
    unsupported_claim_count: int = 0
    conflicted_claim_count: int = 0
    repaired_text: str | None = None


def _ensure_contract(answer_contract: AnswerContract | Mapping[str, Any] | None) -> AnswerContract:
    if answer_contract is None:
        return AnswerContract(
            allowed_facets=[],
            forbidden_facets=[],
            answer_style="single_shop_review",
        )
    if isinstance(answer_contract, AnswerContract):
        return answer_contract
    raw = dict(answer_contract)
    if "allowed_facets" not in raw:
        raw["allowed_facets"] = []
    if "forbidden_facets" not in raw:
        raw["forbidden_facets"] = []
    if not str(raw.get("answer_style") or "").strip():
        raw["answer_style"] = "single_shop_review"
    return AnswerContract.model_validate(raw)

def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key in ("name", "shop_name", "title", "claim", "content", "reason", "summary", "coupon_summary", "why"):
            if key in value:
                parts.append(_flatten_text(value.get(key)))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _chinese_numeral_to_int(text: str) -> int | None:
    compact = str(text or "").strip()
    if not compact:
        return None
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if all(char in digit_map for char in compact):
        try:
            return int("".join(str(digit_map[char]) for char in compact))
        except Exception:
            return None
    if not any(char in unit_map for char in compact):
        return None
    total = 0
    section = 0
    number = 0
    for char in compact:
        if char in digit_map:
            number = digit_map[char]
        elif char in unit_map:
            unit = unit_map[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number


def _normalize_numeric_token(token: str) -> str:
    compact = str(token or "").strip()
    if not compact:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
        return compact.lstrip("0") or "0"
    if re.fullmatch(r"[零〇一二两三四五六七八九十百千万]+", compact):
        parsed = _chinese_numeral_to_int(compact)
        return str(parsed) if parsed is not None else compact
    return compact


def _numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _NUMERIC_PATTERN.finditer(text or ""):
        normalized = _normalize_numeric_token(match.group(0))
        if normalized:
            tokens.add(normalized)
    return tokens


def _content_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.finditer(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", _clean_text(text) or ""):
        token = match.group(0).strip()
        if token:
            tokens.add(token)
    return tokens


def _strict_context_text(answer_context: Any | None) -> list[str]:
    mapping = _as_mapping(answer_context)
    if not mapping:
        return []
    allowed_keys = (
        "answer_branch",
        "answer_style",
        "current_shop",
        "current_topic",
        "selected_entity",
        "selected_shop_id",
        "selected_shop_name",
        "scene",
        "scene_detected",
        "required_facets",
        "confirmed_slots",
        "confirmed_facts",
        "recommendation_count",
        "clarification_slot",
        "missing_slots",
        "fact_draft",
    )
    blobs: list[str] = []
    for key in allowed_keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}, ()):
            blobs.append(_flatten_text(value))
    return blobs


def _source_corpus(
    *,
    answer_context: Any | None,
    answer_contract: AnswerContract,
    topic_name: str,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    facet_result_bundle: Any | None,
    user_need: Any | None,
) -> tuple[set[str], set[str], set[str]]:
    text_blobs: list[str] = [topic_name]
    text_blobs.extend(_strict_context_text(answer_context))
    text_blobs.extend(_flatten_text(candidate) for candidate in ranked_candidates or [])
    text_blobs.extend(_flatten_text(claim) for claim in evidence_claims or [])
    text_blobs.append(_flatten_text(facet_result_bundle))
    text_blobs.append(_flatten_text(user_need))
    text_blobs.append(_flatten_text(answer_contract))
    source_chunks: set[str] = set()
    source_numeric_tokens: set[str] = set()
    source_shop_names: set[str] = set()
    for blob in text_blobs:
        source_chunks.update(_content_tokens(blob))
        source_numeric_tokens.update(_numeric_tokens(blob))
    for candidate in ranked_candidates or []:
        candidate_map = _as_mapping(candidate)
        for key in ("name", "shop_name"):
            value = _clean_text(candidate_map.get(key))
            if value:
                source_shop_names.add(value)
        metadata = _as_mapping(candidate_map.get("structured_features"))
        for key in ("shop_name", "parent_shop_name", "entity_shop_name"):
            value = _clean_text(metadata.get(key))
            if value:
                source_shop_names.add(value)
    for blob in _strict_context_text(answer_context):
        if "店" in blob or "商家" in blob or "门店" in blob:
            source_shop_names.add(blob)
    return source_chunks, source_numeric_tokens, source_shop_names


def _infer_facets_from_text(text: str) -> set[str]:
    compact = (_clean_text(text) or "").replace(" ", "")
    inferred: set[str] = set()
    for facet, keywords in _FACET_KEYWORDS.items():
        if any(keyword in compact for keyword in keywords):
            inferred.add(facet)
    return inferred


def _infer_facets_from_value(value: Any) -> set[str]:
    mapping = _as_mapping(value)
    inferred = set(_infer_facets_from_text(_flatten_text(mapping)))
    for key in ("facet", "facets", "category", "chunk_type", "source_type", "summary_kind", "scene_kind", "chunk_role_label", "source_type_label"):
        raw_value = mapping.get(key)
        if isinstance(raw_value, (list, tuple, set)):
            for item in raw_value:
                inferred.update(_infer_facets_from_text(_clean_text(item) or ""))
        else:
            inferred.update(_infer_facets_from_text(_clean_text(raw_value) or ""))
    metadata = _as_mapping(mapping.get("metadata"))
    inferred.update(_infer_facets_from_value(metadata) if metadata else set())
    return inferred


def _should_keep_facets(
    facets: set[str],
    *,
    allowed_facets: set[str],
    forbidden_facets: set[str],
    allow_recommendation: bool,
) -> bool:
    if not allowed_facets:
        return True
    if allow_recommendation and "recommendation" in allowed_facets:
        return True
    if facets.intersection(forbidden_facets) and not facets.intersection(allowed_facets):
        return False
    return bool(facets.intersection(allowed_facets))


def prune_context_for_contract(
    answer_contract: AnswerContract | Mapping[str, Any] | None,
    *,
    ranked_candidates: Sequence[Mapping[str, Any] | Any] | None,
    evidence_pack: Mapping[str, Any] | Any | None,
    evidence_claims: Sequence[Mapping[str, Any] | Any] | None = None,
) -> dict[str, Any]:
    contract = _ensure_contract(answer_contract)
    allowed_facets = contract.facet_set()
    forbidden_facets = contract.forbidden_facet_set()
    allow_recommendation = bool(contract.allow_recommendation or contract.answer_style in {"multi_shop_recommendation", "comparison"})

    ranked_candidates_list = [_as_mapping(item) for item in ranked_candidates or []]
    kept_candidates: list[dict[str, Any]] = []
    dropped_candidate_count = 0
    for candidate in ranked_candidates_list:
        facets = _infer_facets_from_value(candidate)
        if _should_keep_facets(facets, allowed_facets=allowed_facets, forbidden_facets=forbidden_facets, allow_recommendation=allow_recommendation):
            kept_candidates.append(candidate)
        else:
            dropped_candidate_count += 1

    evidence_pack_map = _as_mapping(evidence_pack)
    evidence_items = [item for item in evidence_pack_map.get("items") or []]
    kept_items: list[dict[str, Any]] = []
    dropped_item_count = 0
    for item in evidence_items:
        item_map = _as_mapping(item)
        facets = _infer_facets_from_value(item_map)
        if _should_keep_facets(facets, allowed_facets=allowed_facets, forbidden_facets=forbidden_facets, allow_recommendation=allow_recommendation):
            kept_items.append(item_map)
        else:
            dropped_item_count += 1

    evidence_claims_list = [_as_mapping(item) for item in evidence_claims or []]
    kept_claims: list[dict[str, Any]] = []
    dropped_claim_count = 0
    for claim in evidence_claims_list:
        facets = _infer_facets_from_value(claim)
        if _should_keep_facets(facets, allowed_facets=allowed_facets, forbidden_facets=forbidden_facets, allow_recommendation=allow_recommendation):
            kept_claims.append(claim)
        else:
            dropped_claim_count += 1

    pruning_summary = {
        "answer_style": contract.answer_style,
        "allowed_facets": list(contract.allowed_facets),
        "forbidden_facets": list(contract.forbidden_facets),
        "kept_facets": list(contract.allowed_facets) if contract.allowed_facets else [],
        "dropped_facets": list(contract.forbidden_facets),
        "allowed_tools": list(contract.allowed_tools),
        "allowed_rag_facets": list(contract.allowed_rag_facets),
        "allow_recommendation": bool(contract.allow_recommendation),
        "allow_extra_context": bool(contract.allow_extra_context),
        "realtime_required": bool(contract.realtime_required),
        "evidence_policy": contract.evidence_policy,
        "kept_ranked_candidate_count": len(kept_candidates),
        "dropped_ranked_candidate_count": dropped_candidate_count,
        "kept_evidence_item_count": len(kept_items),
        "dropped_evidence_item_count": dropped_item_count,
        "kept_evidence_claim_count": len(kept_claims),
        "dropped_evidence_claim_count": dropped_claim_count,
    }

    pruned_evidence_pack = dict(evidence_pack_map)
    if evidence_items:
        pruned_evidence_pack["items"] = kept_items
    if "ranked_candidates" in pruned_evidence_pack:
        pruned_evidence_pack["ranked_candidates"] = []

    return {
        "summary": pruning_summary,
        "ranked_candidates": kept_candidates,
        "evidence_pack": pruned_evidence_pack,
        "evidence_claims": kept_claims,
    }


def lint_answer(
    answer_text: str | None,
    answer_contract: AnswerContract | Mapping[str, Any] | None,
    topic_name: str,
    ranked_candidates: Sequence[Mapping[str, Any] | Any],
    evidence_claims: Sequence[Mapping[str, Any] | Any],
    facet_result_bundle: Any | None = None,
    user_need: Any | None = None,
    answer_context: Any | None = None,
    claim_bindings: Sequence[Mapping[str, Any] | Any] | None = None,
) -> AnswerLintResult:
    if answer_contract is None:
        return AnswerLintResult()
    contract = _ensure_contract(answer_contract)
    text = _clean_text(answer_text)
    compact = text.replace(" ", "")

    issues: list[str] = []
    forbidden_facets: list[str] = []
    repaired_lines: list[str] = []
    blocked = False

    for line in text.splitlines():
        line_facet_violated = False
        line_text = line.replace(" ", "")
        for forbidden in contract.forbidden_facets:
            keywords = _FACET_KEYWORDS.get(forbidden, ())
            if any(keyword in line_text for keyword in keywords):
                if forbidden not in forbidden_facets:
                    forbidden_facets.append(forbidden)
                issues.append(f"forbidden_facet:{forbidden}")
                line_facet_violated = True
                break
        if not line_facet_violated:
            repaired_lines.append(line)

    has_recommendation_language = any(keyword in compact for keyword in _FACET_KEYWORDS["recommendation"])
    if has_recommendation_language and contract.answer_style not in {"multi_shop_recommendation", "comparison", "facet_multi"}:
        issues.append("unsolicited_recommendation")
        blocked = True

    realtime_required = bool(contract.realtime_required or _as_mapping(answer_context).get("realtime_required"))
    if any(keyword in compact for keyword in _DYNAMIC_REaltime_TOKENS) and not realtime_required:
        issues.append("unsupported_realtime_claim")
        blocked = True

    candidate_names = [
        str(item.get("name") or item.get("shop_name") or "").strip()
        for item in (_as_mapping(candidate) for candidate in ranked_candidates)
    ]
    candidate_names = [name for name in candidate_names if name]
    distinct_mentions = [name for name in candidate_names if name and name in text]
    if contract.answer_style in {"coupon_only", "open_status_only", "distance_only", "single_shop_review"} and len(set(distinct_mentions)) > 1:
        issues.append("cross_shop_leak")
        blocked = True

    claim_bindings_list = [
        _as_mapping(item)
        for item in (
            claim_bindings
            or build_claim_bindings(
                answer_text=text,
                answer_contract=contract,
                ranked_candidates=ranked_candidates,
                evidence_claims=evidence_claims,
                facet_result_bundle=facet_result_bundle,
                tool_results=_as_mapping(answer_context).get("tool_results") if isinstance(answer_context, Mapping) else None,
                answer_context=answer_context,
            )
        )
    ]
    claim_summary = summarize_claim_bindings(claim_bindings_list)
    approval_required = bool(_as_mapping(answer_context).get("approval_required"))
    strict_text_check = (
        str(_as_mapping(answer_context).get("answer_branch") or "").strip().lower() in _STRICT_BRANCHES
        or contract.evidence_policy == "strict"
    ) and (
        not claim_bindings_list
        or int(claim_summary.get("unsupported_claim_count") or 0) > 0
        or int(claim_summary.get("partial_claim_count") or 0) > 0
    )
    if strict_text_check:
        source_chunks, source_numeric_tokens, source_shop_names = _source_corpus(
            answer_context=answer_context,
            answer_contract=contract,
            topic_name=topic_name,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            facet_result_bundle=facet_result_bundle,
            user_need=user_need,
        )
        candidate_numeric_tokens = _numeric_tokens(text)
        extra_numeric_tokens = sorted(token for token in candidate_numeric_tokens if token not in source_numeric_tokens)
        if extra_numeric_tokens:
            issues.append("unsupported_numeric_claim")
            blocked = True
        shop_like_mentions = []
        for match in _SHOP_LIKE_PATTERN.finditer(text):
            shop_like_mentions.append(match.group(1).strip())
        for mention in shop_like_mentions:
            if mention in {"这家店", "这家餐厅", "这家饭店", "这家门店", "这家商家"}:
                continue
            if mention == topic_name or any(source_name and source_name in mention for source_name in source_shop_names):
                continue
            issues.append("unsupported_shop_name")
            blocked = True
            break
        candidate_chunks = _content_tokens(text)
        extra_chunks = sorted(
            token
            for token in candidate_chunks
            if token not in source_chunks and token not in _STRICT_GENERIC_TOKENS and token not in candidate_names
        )
        if extra_chunks:
            issues.append("unsupported_factual_phrase")
            blocked = True

    high_risk = is_high_risk_answer_context(
        answer_contract=contract,
        answer_context=answer_context,
        claim_bindings=claim_bindings_list,
    )
    for binding in claim_bindings_list:
        status = str(binding.get("support_status") or "").strip().lower()
        claim_id = str(binding.get("claim_id") or "").strip() or "claim"
        claim_type = str(binding.get("claim_type") or "").strip().lower()
        policy = claim_policy_for_facet(
            binding.get("facet") or claim_type,
            answer_style=contract.answer_style,
            approval_required=approval_required,
        )
        if status in {"unsupported", "conflicted"}:
            issues.append(f"unsupported_claim:{claim_id}")
            if high_risk or policy.high_risk or claim_type in _TOOL_REQUIRED_CLAIMS or claim_type in _RAG_REQUIRED_CLAIMS or claim_type in _HYBRID_CLAIMS:
                blocked = True
        elif status == "partial":
            issues.append(f"partial_claim:{claim_id}")
        primary_source_type = str(binding.get("primary_source_type") or "").strip().lower()
        if policy.allowed_primary_source_types and primary_source_type not in policy.allowed_primary_source_types:
            issues.append(f"claim_source_mismatch:{claim_id}")
            if policy.high_risk or high_risk:
                blocked = True

    cleaned_text = "\n".join(repaired_lines).strip()
    if not cleaned_text and text:
        cleaned_text = text.strip()
    severity: Literal["pass", "warn", "block"]
    if blocked:
        severity = "block"
    elif issues:
        severity = "warn"
    else:
        severity = "pass"

    return AnswerLintResult(
        passed=not issues,
        severity=severity,
        issues=issues,
        forbidden_facets=forbidden_facets,
        cross_shop_leak="cross_shop_leak" in issues,
        unsupported_realtime_claim="unsupported_realtime_claim" in issues,
        unsolicited_recommendation="unsolicited_recommendation" in issues,
        claim_bindings=claim_bindings_list,
        claim_count=int(claim_summary.get("claim_count") or 0),
        supported_claim_count=int(claim_summary.get("supported_claim_count") or 0),
        partial_claim_count=int(claim_summary.get("partial_claim_count") or 0),
        unsupported_claim_count=int(claim_summary.get("unsupported_claim_count") or 0),
        conflicted_claim_count=int(claim_summary.get("conflicted_claim_count") or 0),
        repaired_text=cleaned_text or None,
    )
