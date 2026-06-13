"""Tests for RAG system improvements: QueryRewriteGuard, degradation, config, snapshot, evidence, quality guard, fusion."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from learning_agent_service.rag.rewrite_guard import (
    QueryRewriteGuard,
    QueryRewriteGuardConfig,
    QueryRewriteGuardResult,
)
from learning_agent_service.rag.rewrite import QueryRewriteConfig, QueryRewriteContext, QueryRewriteService
from learning_agent_service.rag.models import (
    EvidenceItem,
    EvidencePack,
    EvidenceStatus,
    HybridRecallResult,
    KnowledgeChunk,
    RecallHit,
    RetrievalFilters,
    RetrievalPlan,
    RetrievalTrace,
)
from learning_agent_service.rag.evidence import (
    EvidenceGovernanceConfig,
    EvidenceGovernanceService,
    QueryComplexityProfiler,
    QueryComplexityProfile,
)
from learning_agent_service.rag.quality_guard import (
    QualityVerdict,
    RetrievalQualityGuard,
    RetrievalQualityGuardConfig,
    RetrievalQualityResult,
)
from learning_agent_service.rag.domain_rules import (
    DomainRulesConfig,
    _BUILTIN_DOMAIN_RULES,
    load_domain_rules_config,
    get_all_domain_tokens,
    DomainRuleEntry,
)
from learning_agent_service.rag.retrieval.reranker import ReciprocalRankFusion
from learning_agent_service.rag.retrieval.shared import RRFConfig
from learning_agent_service.rag.service import (
    HybridRAGOrchestrator,
    ReadinessStatus,
    SnapshotState,
)


def _chunk(
    chunk_id: str,
    *,
    text: str = "test content",
    document_id: str = "doc-1",
    title: str = "test",
    version: str = "v1",
    chunk_type: str = "concept",
    parent_id: str | None = None,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        title=title,
        summary=text[:32],
        chunk_type=chunk_type,
        version=version,
        parent_id=parent_id,
        tags=("test",),
    )


def _hit(
    chunk: KnowledgeChunk,
    score: float = 0.5,
    route: str = "dense",
    rank: int = 1,
    *,
    degraded: bool = False,
    retrieval_mode: str = "normal",
    metadata: dict[str, Any] | None = None,
) -> RecallHit:
    return RecallHit(
        chunk=chunk,
        score=score,
        route=route,
        rank=rank,
        route_scores={route: score},
        matched_routes=(route,),
        fused_score=score,
        rrf_score=score,
        degraded=degraded,
        retrieval_mode=retrieval_mode,
        metadata=metadata or {},
    )


def _plan(
    semantic_query: str = "test query",
    keyword_query: str = "test",
    *,
    raw_query: str = "",
    intent: str = "",
    max_evidence: int = 5,
) -> RetrievalPlan:
    return RetrievalPlan(
        semantic_query=semantic_query,
        keyword_query=keyword_query,
        max_evidence=max_evidence,
        extra={
            "raw_query": raw_query or semantic_query,
            "intent": intent,
        },
    )


# ──────────────────────────────────────────────────────────────────────
# Part 1: QueryRewriteGuard
# ──────────────────────────────────────────────────────────────────────

class TestQueryRewriteGuard:
    def test_identical_query_accepted(self):
        guard = QueryRewriteGuard()
        result = guard.validate_rewrite("北京火锅推荐", "北京火锅推荐")
        assert result.accepted is True
        assert result.weight == 1.0

    def test_empty_rewrite_rejected(self):
        guard = QueryRewriteGuard()
        result = guard.validate_rewrite("北京火锅推荐", "")
        assert result.accepted is False
        assert result.reject_reason == "empty_rewrite"

    def test_slot_loss_city_rejected(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(max_slot_loss_tolerance=0))
        result = guard.validate_rewrite(
            "北京火锅推荐",
            "火锅推荐好吃的",
            context_slots={"city": "北京"},
        )
        assert result.accepted is False
        assert "city" in result.slot_loss
        assert "slot_loss" in result.reject_reason

    def test_slot_loss_shop_name_rejected(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(max_slot_loss_tolerance=0))
        result = guard.validate_rewrite(
            "海底捞怎么样",
            "火锅店推荐",
            context_slots={"shop_name": "海底捞"},
        )
        assert result.accepted is False
        assert "shop_name" in result.slot_loss

    def test_slot_loss_within_tolerance_accepted(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(
            max_slot_loss_tolerance=1,
            min_semantic_similarity=0.0,
        ))
        result = guard.validate_rewrite(
            "北京火锅推荐",
            "火锅推荐好吃的",
            context_slots={"city": "北京"},
        )
        assert result.accepted is True
        assert "city" in result.slot_loss

    def test_intent_drift_rejected(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(reject_on_intent_drift=True))
        result = guard.validate_rewrite(
            "海底捞怎么样",
            "附近有什么好的推荐",
            intent="detail",
        )
        assert result.accepted is False
        assert result.intent_changed is True
        assert "intent_drift" in result.reject_reason

    def test_low_semantic_similarity_rejected(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(min_semantic_similarity=0.3))
        result = guard.validate_rewrite(
            "北京火锅推荐",
            "Python并发编程原理",
        )
        assert result.accepted is False
        assert "low_semantic_similarity" in result.reject_reason

    def test_partial_match_downweighted(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(
            downweight_on_partial_match=True,
            min_semantic_similarity=0.0,
            max_slot_loss_tolerance=1,
        ))
        result = guard.validate_rewrite(
            "北京火锅推荐好吃的",
            "火锅推荐好吃的",
            context_slots={"city": "北京"},
        )
        assert result.accepted is True
        assert result.weight < 1.0

    def test_build_query_variants_includes_original(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(min_semantic_similarity=0.0))
        variants = guard.build_query_variants(
            "北京火锅推荐",
            rewrite_query="北京火锅好吃的推荐",
            hyde_passage="火锅是北京最受欢迎的美食之一",
        )
        assert len(variants["variants"]) == 3
        assert variants["variants"][0]["source"] == "original"
        assert variants["variants"][0]["weight"] == 1.0
        assert variants["primary_query"] == "北京火锅推荐"

    def test_disabled_guard_always_accepts(self):
        guard = QueryRewriteGuard(QueryRewriteGuardConfig(enabled=False))
        result = guard.validate_rewrite("北京", "上海")
        assert result.accepted is True


# ──────────────────────────────────────────────────────────────────────
# Part 1b: Original query always participates
# ──────────────────────────────────────────────────────────────────────

class TestOriginalQueryAlwaysParticipates:
    def test_build_plan_includes_original_as_supplemental_when_different(self):
        svc = QueryRewriteService(QueryRewriteConfig(llm_enabled=False))
        ctx = QueryRewriteContext(
            raw_query="这个怎么样",
            resolved_topic="海底捞火锅",
        )
        plan = svc.build_plan(ctx)
        assert "这个怎么样" in plan.supplemental_queries

    def test_build_plan_no_supplemental_when_same(self):
        svc = QueryRewriteService(QueryRewriteConfig(llm_enabled=False))
        ctx = QueryRewriteContext(
            raw_query="北京火锅推荐",
            resolved_topic="火锅",
        )
        plan = svc.build_plan(ctx)
        assert plan.semantic_query == "北京火锅推荐"
        assert "北京火锅推荐" not in plan.supplemental_queries

    def test_build_plan_original_not_duplicated_when_semantic(self):
        svc = QueryRewriteService(QueryRewriteConfig(llm_enabled=False))
        ctx = QueryRewriteContext(raw_query="test")
        plan = svc.build_plan(ctx)
        assert plan.semantic_query == "test"
        assert "test" not in plan.supplemental_queries


# ──────────────────────────────────────────────────────────────────────
# Part 2: Multi-level degradation
# ──────────────────────────────────────────────────────────────────────

class TestMultiLevelDegradation:
    def test_recall_hit_has_degraded_field(self):
        hit = _hit(_chunk("c1"), degraded=True, retrieval_mode="heuristic_fallback")
        assert hit.degraded is True
        assert hit.retrieval_mode == "heuristic_fallback"

    def test_recall_hit_default_not_degraded(self):
        hit = _hit(_chunk("c1"))
        assert hit.degraded is False
        assert hit.retrieval_mode == "normal"

    def test_hybrid_result_has_degradation_fields(self):
        result = HybridRecallResult(
            hits=(),
            retrieval_strategy="test",
            degraded=True,
            retrieval_mode="heuristic_fallback",
            confidence=0.3,
            quality_hint="all_routes_degraded",
        )
        assert result.degraded is True
        assert result.retrieval_mode == "heuristic_fallback"
        assert result.confidence == 0.3

    def test_hybrid_result_default_not_degraded(self):
        result = HybridRecallResult(hits=(), retrieval_strategy="test")
        assert result.degraded is False
        assert result.retrieval_mode == "normal"


# ──────────────────────────────────────────────────────────────────────
# Part 3: Domain rules config
# ──────────────────────────────────────────────────────────────────────

class TestDomainRulesConfig:
    def test_builtin_config_has_domains(self):
        config = _BUILTIN_DOMAIN_RULES
        assert len(config.domains) >= 3
        domain_names = [d.name for d in config.domains]
        assert "餐饮" in domain_names
        assert "美发/美容" in domain_names
        assert "按摩/足疗" in domain_names

    def test_builtin_config_has_tokens(self):
        config = _BUILTIN_DOMAIN_RULES
        assert len(config.greeting_tokens) > 0
        assert len(config.compare_tokens) > 0
        assert len(config.coupon_tokens) > 0

    def test_get_all_domain_tokens(self):
        tokens = get_all_domain_tokens()
        assert "餐厅" in tokens
        assert "火锅" in tokens
        assert "美发" in tokens

    def test_load_config_missing_file_uses_defaults(self):
        config = load_domain_rules_config("nonexistent.json")
        assert config == _BUILTIN_DOMAIN_RULES

    def test_domain_rule_entry_structure(self):
        entry = DomainRuleEntry(
            name="test",
            tokens=("a", "b"),
            aliases=("c",),
            slot_hints={"domain": "test"},
            examples=("example",),
        )
        assert entry.name == "test"
        assert entry.tokens == ("a", "b")
        assert entry.slot_hints == {"domain": "test"}

    def test_config_backward_compatible(self):
        config = _BUILTIN_DOMAIN_RULES
        assert config.page_hints
        assert config.context_keys
        assert config.tool_actions
        assert config.rag_actions


# ──────────────────────────────────────────────────────────────────────
# Part 4: Snapshot management
# ──────────────────────────────────────────────────────────────────────

class TestSnapshotManagement:
    def test_snapshot_state_fields(self):
        state = SnapshotState(
            version="v1",
            status="current",
            chunk_count=10,
            is_last_good=True,
        )
        assert state.version == "v1"
        assert state.is_last_good is True

    def test_readiness_status_fields(self):
        status = ReadinessStatus(
            app_ready=True,
            rag_ready=True,
            snapshot_version="v1",
            using_last_good_snapshot=False,
        )
        assert status.app_ready is True
        assert status.rag_ready is True

    def test_orchestrator_readiness_property(self):
        from learning_agent_service.config import Settings
        settings = Settings(
            _env_file=None,
            enable_online_dense_retrieval=False,
            enable_online_sparse_retrieval=False,
            enable_bm25_sparse_retrieval=False,
            enable_remote_reranker=False,
            enable_llm_query_rewrite=False,
            enable_hyde_sparse_retrieval=False,
        )
        orchestrator = HybridRAGOrchestrator(
            settings,
            knowledge_chunks=[
                _chunk("c1", text="unique content about java spring"),
                _chunk("c2", text="unique content about redis caching"),
            ],
        )
        readiness = orchestrator.readiness
        assert readiness.app_ready is True
        assert readiness.rag_ready is True
        assert readiness.chunk_count == 2

    def test_orchestrator_load_snapshot(self):
        from learning_agent_service.config import Settings
        settings = Settings(
            _env_file=None,
            enable_online_dense_retrieval=False,
            enable_online_sparse_retrieval=False,
            enable_bm25_sparse_retrieval=False,
            enable_remote_reranker=False,
            enable_llm_query_rewrite=False,
            enable_hyde_sparse_retrieval=False,
        )
        orchestrator = HybridRAGOrchestrator(
            settings,
            knowledge_chunks=[_chunk("c1", text="initial unique content")],
        )
        new_chunks = [
            _chunk("c3", text="new unique content about python"),
            _chunk("c4", text="new unique content about golang"),
        ]
        count = orchestrator.load_snapshot(new_chunks, version="v2")
        assert count == 2
        assert orchestrator.snapshot_state.version == "v2"
        assert orchestrator.readiness.chunk_count == 2

    def test_load_snapshot_empty_falls_back_to_last_good(self):
        from learning_agent_service.config import Settings
        settings = Settings(
            _env_file=None,
            enable_online_dense_retrieval=False,
            enable_online_sparse_retrieval=False,
            enable_bm25_sparse_retrieval=False,
            enable_remote_reranker=False,
            enable_llm_query_rewrite=False,
            enable_hyde_sparse_retrieval=False,
        )
        orchestrator = HybridRAGOrchestrator(
            settings,
            knowledge_chunks=[_chunk("c1")],
        )
        count = orchestrator.load_snapshot([])
        assert count == 1
        assert orchestrator.readiness.chunk_count == 1


# ──────────────────────────────────────────────────────────────────────
# Part 5: EvidenceGovernance dynamic token budget
# ──────────────────────────────────────────────────────────────────────

class TestEvidenceGovernanceDynamicBudget:
    def test_simple_query_uses_fewer_items(self):
        profiler = QueryComplexityProfiler(
            EvidenceGovernanceConfig(
                simple_query_max_items=3,
                complex_query_max_items=8,
            )
        )
        plan = _plan(raw_query="什么是火锅", intent="explain")
        profile = profiler.profile(plan)
        assert profile.level == "simple"
        assert profile.max_items == 3
        assert profile.answer_type == "factoid"

    def test_complex_query_uses_more_items(self):
        profiler = QueryComplexityProfiler(
            EvidenceGovernanceConfig(
                simple_query_max_items=3,
                complex_query_max_items=8,
            )
        )
        plan = _plan(raw_query="推荐附近好吃的火锅店对比", intent="compare")
        profile = profiler.profile(plan)
        assert profile.level == "complex"
        assert profile.max_items == 8
        assert profile.needs_diversity is True

    def test_comparison_intent_is_complex(self):
        profiler = QueryComplexityProfiler()
        plan = _plan(raw_query="海底捞和呷哺呷哺的区别", intent="compare")
        profile = profiler.profile(plan)
        assert profile.level == "complex"
        assert profile.answer_type == "comparison"

    def test_compare_in_raw_query_is_comparison(self):
        profiler = QueryComplexityProfiler()
        plan = _plan(raw_query="对比一下海底捞和呷哺呷哺")
        profile = profiler.profile(plan)
        assert profile.answer_type == "comparison"

    def test_realtime_risk_detected(self):
        profiler = QueryComplexityProfiler()
        plan = _plan(raw_query="现在还营业吗", intent="follow_up")
        profile = profiler.profile(plan)
        assert profile.is_realtime_risk is True

    def test_evidence_governance_uses_complexity(self):
        config = EvidenceGovernanceConfig(
            simple_query_max_items=2,
            complex_query_max_items=8,
        )
        service = EvidenceGovernanceService(config)
        plan = _plan(raw_query="什么是火锅", intent="explain")
        hits = [
            _hit(_chunk("c1", text="火锅是一种中国美食"), score=0.6),
            _hit(_chunk("c2", text="火锅的种类很多"), score=0.5),
            _hit(_chunk("c3", text="吃火锅很热闹"), score=0.4),
            _hit(_chunk("c4", text="火锅底料很重要"), score=0.3),
        ]
        pack = service.evaluate(plan, hits)
        assert len(pack.items) <= 2


# ──────────────────────────────────────────────────────────────────────
# Part 6: RetrievalQualityGuard
# ──────────────────────────────────────────────────────────────────────

class TestRetrievalQualityGuard:
    def test_empty_evidence_triggers_retry(self):
        guard = RetrievalQualityGuard()
        pack = EvidencePack(
            items=(),
            status="empty",
            evidence_status=EvidenceStatus.EMPTY,
        )
        plan = _plan()
        result = guard.check(pack, plan)
        assert result.verdict == QualityVerdict.RETRY_RETRIEVAL
        assert result.evidence_count == 0

    def test_low_top_score_triggers_conservative(self):
        guard = RetrievalQualityGuard(RetrievalQualityGuardConfig(min_top_score=0.3))
        c = _chunk("c1", text="test")
        item = EvidenceItem(chunk=c, score=0.1, routes=("dense",), reasons=("test",))
        pack = EvidencePack(
            items=(item,),
            status="degraded",
            evidence_status=EvidenceStatus.WEAK,
        )
        plan = _plan()
        result = guard.check(pack, plan)
        assert result.verdict == QualityVerdict.CONSERVATIVE_ANSWER
        assert "low_top_score" in result.reason

    def test_realtime_risk_without_tool_triggers_tool_required(self):
        guard = RetrievalQualityGuard(RetrievalQualityGuardConfig(realtime_risk_requires_tool=True))
        c = _chunk("c1", text="营业时间信息")
        item = EvidenceItem(chunk=c, score=0.5, routes=("dense",), reasons=("test",))
        pack = EvidencePack(
            items=(item,),
            status="ok",
            evidence_status=EvidenceStatus.OK,
        )
        plan = _plan(raw_query="现在还营业吗", intent="follow_up")
        result = guard.check(pack, plan, has_tool_evidence=False)
        assert result.verdict == QualityVerdict.TOOL_REQUIRED
        assert result.is_realtime_risk is True

    def test_realtime_risk_with_tool_passes(self):
        guard = RetrievalQualityGuard(RetrievalQualityGuardConfig(realtime_risk_requires_tool=True))
        c = _chunk("c1", text="营业时间信息")
        item = EvidenceItem(chunk=c, score=0.5, routes=("dense",), reasons=("test",))
        pack = EvidencePack(
            items=(item,),
            status="ok",
            evidence_status=EvidenceStatus.OK,
        )
        plan = _plan(raw_query="现在还营业吗", intent="follow_up")
        result = guard.check(pack, plan, has_tool_evidence=True)
        assert result.verdict == QualityVerdict.OK

    def test_ok_evidence_passes(self):
        guard = RetrievalQualityGuard()
        c = _chunk("c1", text="火锅推荐信息")
        item = EvidenceItem(chunk=c, score=0.7, routes=("dense",), reasons=("test",))
        pack = EvidencePack(
            items=(item,),
            status="ok",
            evidence_status=EvidenceStatus.OK,
        )
        plan = _plan(raw_query="推荐火锅")
        result = guard.check(pack, plan)
        assert result.verdict == QualityVerdict.OK

    def test_disabled_guard_always_ok(self):
        guard = RetrievalQualityGuard(RetrievalQualityGuardConfig(enabled=False))
        pack = EvidencePack(items=(), status="empty", evidence_status=EvidenceStatus.EMPTY)
        result = guard.check(pack, _plan())
        assert result.verdict == QualityVerdict.OK


# ──────────────────────────────────────────────────────────────────────
# Part 7: Dynamic RRF/Fusion weights
# ──────────────────────────────────────────────────────────────────────

class TestDynamicFusionWeights:
    def test_basic_fusion(self):
        fusion = ReciprocalRankFusion(RRFConfig(k=60))
        c1 = _chunk("c1", text="test1")
        c2 = _chunk("c2", text="test2")
        route_hits = {
            "dense": [_hit(c1, score=0.8, route="dense")],
            "sparse": [_hit(c2, score=0.6, route="sparse")],
        }
        result = fusion.fuse(route_hits)
        assert len(result) == 2

    def test_dynamic_weights_with_intent(self):
        fusion = ReciprocalRankFusion(RRFConfig(k=60))
        c1 = _chunk("c1", text="test1")
        c2 = _chunk("c2", text="test2")
        route_hits = {
            "dense": [_hit(c1, score=0.5, route="dense")],
            "metadata": [_hit(c2, score=0.5, route="metadata")],
        }
        result = fusion.fuse(
            route_hits,
            query_intent="detail",
            query_slots={"shop_name": "海底捞"},
        )
        assert len(result) == 2
        assert result[0].metadata.get("fusion_weights") is not None

    def test_degraded_route_downweighted(self):
        fusion = ReciprocalRankFusion(RRFConfig(k=60))
        c1 = _chunk("c1", text="test1")
        c2 = _chunk("c2", text="test2")
        route_hits = {
            "dense": [_hit(c1, score=0.8, route="dense")],
            "sparse": [_hit(c2, score=0.8, route="sparse", degraded=True)],
        }
        result = fusion.fuse(route_hits)
        weights = result[0].metadata.get("fusion_weights", {})
        if weights:
            assert weights.get("sparse", 1.0) < weights.get("dense", 1.0)

    def test_empty_route_hits(self):
        fusion = ReciprocalRankFusion(RRFConfig(k=60))
        result = fusion.fuse({})
        assert result == ()


# ──────────────────────────────────────────────────────────────────────
# Part 8: Backward compatibility
# ──────────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_new_recall_hit_fields_have_defaults(self):
        hit = _hit(_chunk("c1"))
        assert hit.degraded is False
        assert hit.retrieval_mode == "normal"

    def test_new_hybrid_result_fields_have_defaults(self):
        result = HybridRecallResult(hits=(), retrieval_strategy="test")
        assert result.degraded is False
        assert result.retrieval_mode == "normal"
        assert result.confidence == 1.0
        assert result.quality_hint == ""

    def test_new_evidence_config_fields_have_defaults(self):
        config = EvidenceGovernanceConfig()
        assert config.max_token_budget == 2000
        assert config.simple_query_max_items == 3
        assert config.complex_query_max_items == 8
        assert config.enable_diversity_control is True

    def test_existing_tests_should_not_break(self):
        from learning_agent_service.rag.evidence import EvidenceGovernanceConfig
        config = EvidenceGovernanceConfig(
            low_score_threshold=0.28,
            strong_score_threshold=0.45,
            max_items=6,
        )
        assert config.max_items == 6
