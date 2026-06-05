from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from learning_agent_service.domain.utils import as_mapping as _as_mapping, clean_text as _clean_text

from .answer_contract import AnswerContract

_FACET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coupon": ("券", "优惠", "代金券", "团购", "折扣", "打折"),
    "open_status": ("营业", "开门", "开业", "营业时间", "关门"),
    "distance_eta": ("距离", "有多远", "公里", "路程", "怎么走", "怎么去", "导航"),
    "price": ("人均", "预算", "价格", "元"),
    "scene_fit": ("适合", "约会", "家庭", "长辈", "带娃", "安静", "停车"),
    "environment": ("环境", "氛围", "安静", "吵", "包间"),
    "taste": ("口味", "味道", "好吃", "菜"),
    "service": ("服务", "态度", "排队"),
    "recommendation": ("推荐", "优先推荐", "这几家", "几家"),
}
_DYNAMIC_REaltime_TOKENS = ("实时", "现在", "刚查", "最新", "当前")


class AnswerLintResult(BaseModel):
    passed: bool = True
    severity: Literal["pass", "warn", "block"] = "pass"
    issues: list[str] = Field(default_factory=list)
    forbidden_facets: list[str] = Field(default_factory=list)
    cross_shop_leak: bool = False
    unsupported_realtime_claim: bool = False
    unsolicited_recommendation: bool = False
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
    if "answer_style" not in raw:
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

    if any(keyword in compact for keyword in _DYNAMIC_REaltime_TOKENS) and not contract.realtime_required:
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

    cleaned_text = "\n".join(repaired_lines).strip()
    if not cleaned_text and text:
        cleaned_text = text.strip()
    if forbidden_facets and not cleaned_text:
        blocked = True

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
        repaired_text=cleaned_text or None,
    )
