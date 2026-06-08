from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .answer_planner import (
        CandidateEvidenceSummary,
        CouponAdvice,
        EvidenceItem,
        EvidencePack,
        GroundedVerificationResult,
        LocalLifeAnswerPlan,
        NextAction,
        SceneFitSummary,
        build_answer_planner_request,
        parse_answer_plan_payload,
    )
    from .assistant import LocalLifeModelAssistant
    from .catalog import LocalLifeCatalog, get_default_catalog
    from .context_arbitration import ContextArbitration
    from .evidence_pack import build_evidence_pack
    from .evidence_scope_guard import EvidenceScopeGuard
    from .grounded_verifier import GroundedVerifier
    from .graph_state import (
        InputContext,
        MemoryArbitrationPolicy,
        MemoryArbitrationResult,
        PerceptionContext,
        build_input_context,
        build_memory_arbitration_result,
        build_perception_context,
    )
    from .query_rewriter import normalize_query
    from .query_router import LocalLifeQueryRouter, LocalLifeRouteDecision
    from .ranker import rank_candidate, rank_candidates
    from .response_builder import build_response_bundle
    from .slot_extractor import extract_slots

__all__ = [
    "LocalLifeCatalog",
    "LocalLifeModelAssistant",
    "LocalLifeQueryRouter",
    "LocalLifeRouteDecision",
    "LocalLifeAnswerPlan",
    "CandidateEvidenceSummary",
    "CouponAdvice",
    "EvidenceItem",
    "EvidencePack",
    "GroundedVerificationResult",
    "GroundedVerifier",
    "ContextArbitration",
    "EvidenceScopeGuard",
    "InputContext",
    "MemoryArbitrationPolicy",
    "MemoryArbitrationResult",
    "NextAction",
    "PerceptionContext",
    "SceneFitSummary",
    "build_answer_planner_request",
    "build_input_context",
    "build_evidence_pack",
    "build_memory_arbitration_result",
    "build_response_bundle",
    "build_perception_context",
    "extract_slots",
    "get_default_catalog",
    "rank_candidate",
    "rank_candidates",
    "parse_answer_plan_payload",
    "normalize_query",
]


def __getattr__(name: str) -> Any:
    if name in {
        "CandidateEvidenceSummary",
        "CouponAdvice",
        "EvidenceItem",
        "EvidencePack",
        "GroundedVerificationResult",
        "LocalLifeAnswerPlan",
        "NextAction",
        "SceneFitSummary",
        "build_answer_planner_request",
        "parse_answer_plan_payload",
    }:
        from .answer_planner import (
            CandidateEvidenceSummary as value_CandidateEvidenceSummary,
            CouponAdvice as value_CouponAdvice,
            EvidenceItem as value_EvidenceItem,
            EvidencePack as value_EvidencePack,
            GroundedVerificationResult as value_GroundedVerificationResult,
            LocalLifeAnswerPlan as value_LocalLifeAnswerPlan,
            NextAction as value_NextAction,
            SceneFitSummary as value_SceneFitSummary,
            build_answer_planner_request as value_build_answer_planner_request,
            parse_answer_plan_payload as value_parse_answer_plan_payload,
        )

        value_map = {
            "CandidateEvidenceSummary": value_CandidateEvidenceSummary,
            "CouponAdvice": value_CouponAdvice,
            "EvidenceItem": value_EvidenceItem,
            "EvidencePack": value_EvidencePack,
            "GroundedVerificationResult": value_GroundedVerificationResult,
            "LocalLifeAnswerPlan": value_LocalLifeAnswerPlan,
            "NextAction": value_NextAction,
            "SceneFitSummary": value_SceneFitSummary,
            "build_answer_planner_request": value_build_answer_planner_request,
            "parse_answer_plan_payload": value_parse_answer_plan_payload,
        }
        return value_map[name]
    if name == "LocalLifeModelAssistant":
        from .assistant import LocalLifeModelAssistant as value

        return value
    if name in {"LocalLifeCatalog", "get_default_catalog"}:
        from .catalog import LocalLifeCatalog as value_LocalLifeCatalog, get_default_catalog as value_get_default_catalog

        return {
            "LocalLifeCatalog": value_LocalLifeCatalog,
            "get_default_catalog": value_get_default_catalog,
        }[name]
    if name == "ContextArbitration":
        from .context_arbitration import ContextArbitration as value

        return value
    if name == "build_evidence_pack":
        from .evidence_pack import build_evidence_pack as value

        return value
    if name == "EvidenceScopeGuard":
        from .evidence_scope_guard import EvidenceScopeGuard as value

        return value
    if name == "GroundedVerifier":
        from .grounded_verifier import GroundedVerifier as value

        return value
    if name in {
        "InputContext",
        "MemoryArbitrationPolicy",
        "MemoryArbitrationResult",
        "PerceptionContext",
        "build_input_context",
        "build_memory_arbitration_result",
        "build_perception_context",
    }:
        from .graph_state import (
            InputContext as value_InputContext,
            MemoryArbitrationPolicy as value_MemoryArbitrationPolicy,
            MemoryArbitrationResult as value_MemoryArbitrationResult,
            PerceptionContext as value_PerceptionContext,
            build_input_context as value_build_input_context,
            build_memory_arbitration_result as value_build_memory_arbitration_result,
            build_perception_context as value_build_perception_context,
        )

        value_map = {
            "InputContext": value_InputContext,
            "MemoryArbitrationPolicy": value_MemoryArbitrationPolicy,
            "MemoryArbitrationResult": value_MemoryArbitrationResult,
            "PerceptionContext": value_PerceptionContext,
            "build_input_context": value_build_input_context,
            "build_memory_arbitration_result": value_build_memory_arbitration_result,
            "build_perception_context": value_build_perception_context,
        }
        return value_map[name]
    if name == "normalize_query":
        from .query_rewriter import normalize_query as value

        return value
    if name in {"LocalLifeQueryRouter", "LocalLifeRouteDecision"}:
        from .query_router import LocalLifeQueryRouter as value_LocalLifeQueryRouter, LocalLifeRouteDecision as value_LocalLifeRouteDecision

        return {
            "LocalLifeQueryRouter": value_LocalLifeQueryRouter,
            "LocalLifeRouteDecision": value_LocalLifeRouteDecision,
        }[name]
    if name in {"rank_candidate", "rank_candidates"}:
        from .ranker import rank_candidate as value_rank_candidate, rank_candidates as value_rank_candidates

        return {"rank_candidate": value_rank_candidate, "rank_candidates": value_rank_candidates}[name]
    if name == "build_response_bundle":
        from .response_builder import build_response_bundle as value

        return value
    if name == "extract_slots":
        from .slot_extractor import extract_slots as value

        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
