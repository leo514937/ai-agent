from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import _bootstrap  # noqa: F401

from learning_agent_service.config import Settings
from learning_agent_service.config import settings as settings_module
from learning_agent_service.domain.enums import IntentType
from learning_agent_service.domain.guards import evaluate_clarification, validate_memory_record_mutation
from learning_agent_service.domain.memory import (
    MemoryCandidate,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryTargetStore,
    MemoryType,
)
from learning_agent_service.memory import (
    MemoryConflictPolicyConfig,
    MemoryConflictResolver,
    MemoryGovernancePolicy,
    MemoryGovernancePolicyConfig,
    MemoryPromotionPolicy,
    PromotionConfig,
)
from learning_agent_service.memory.models import (
    ExplicitUserSignals,
    MemoryPromotionInput,
    PersistentSessionContext,
    UserPreferenceProfile,
)


class PolicySettingsAndGuardsTestCase(unittest.TestCase):
    def _build_record(self, *, status: MemoryStatus = MemoryStatus.ACTIVE, confidence: float = 0.9, stability: float = 0.9) -> MemoryRecord:
        return MemoryRecord(
            memory_id="memory-1",
            user_id="user-1",
            session_id="session-1",
            topic="policy",
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.USER,
            status=status,
            source=MemorySource.MODEL_INFERRED,
            confidence=confidence,
            importance=0.8,
            stability=stability,
            sensitivity=MemorySensitivity.PUBLIC,
            summary="策略测试",
            content={"fact": "memory"},
            source_turn_id="turn-1",
        )

    def test_settings_env_values_flow_into_policy_settings(self) -> None:
        env = {
            "LEARNING_AGENT_INTENT_CONFIDENCE_THRESHOLD": "0.72",
            "LEARNING_AGENT_REFERENCE_RESOLUTION_CONFIDENCE_THRESHOLD": "0.81",
            "LEARNING_AGENT_METADATA_FILTER_CONFIDENCE_THRESHOLD": "0.93",
            "LEARNING_AGENT_MEMORY_RETRIEVAL_PROMPT_LIMIT": "7",
            "LEARNING_AGENT_MEMORY_RETRIEVAL_STATE_LIMIT": "6",
            "LEARNING_AGENT_MEMORY_RETRIEVAL_RAG_LIMIT": "5",
            "LEARNING_AGENT_MEMORY_RETRIEVAL_TOOL_LIMIT": "4",
            "LEARNING_AGENT_MEMORY_RETRIEVAL_TOKEN_BUDGET": "900",
            "LEARNING_AGENT_MEMORY_INJECTION_PROMPT_LIMIT": "8",
            "LEARNING_AGENT_MEMORY_INJECTION_STATE_LIMIT": "9",
            "LEARNING_AGENT_MEMORY_INJECTION_TOOL_LIMIT": "6",
            "LEARNING_AGENT_MEMORY_INJECTION_RAG_LIMIT": "7",
            "LEARNING_AGENT_MEMORY_INJECTION_TOKEN_BUDGET": "1000",
            "LEARNING_AGENT_MEMORY_GOVERNANCE_LOW_CONFIDENCE_THRESHOLD": "0.22",
            "LEARNING_AGENT_MEMORY_GOVERNANCE_LOW_STABILITY_THRESHOLD": "0.33",
            "LEARNING_AGENT_MEMORY_CONFLICT_SUPERSEDE_MARGIN": "0.12",
            "LEARNING_AGENT_MEMORY_CONFLICT_MERGE_SIMILARITY_THRESHOLD": "0.77",
            "LEARNING_AGENT_MEMORY_PROMOTION_PREFERENCE_PROMOTE_COUNT": "4",
            "LEARNING_AGENT_CONSOLIDATION_MINIMUM_DUPLICATE_GROUP_SIZE": "3",
            "LEARNING_AGENT_CONSOLIDATION_MAX_CONFLICTS": "4",
            "LEARNING_AGENT_CONSOLIDATION_CONFIRMED_EXPLICITNESS": "1.25",
            "LEARNING_AGENT_CONSOLIDATION_INFERRED_EXPLICITNESS": "0.25",
            "LEARNING_AGENT_CONSOLIDATION_RECENCY_WINDOW_SECONDS": "604800",
            "LEARNING_AGENT_ORCHESTRATOR_CONFIRMED_CONFIDENCE_THRESHOLD": "0.91",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()
            policy = settings.policy_settings()

        self.assertEqual(policy.workflow_understanding.intent_confidence_threshold, 0.72)
        self.assertEqual(policy.workflow_understanding.reference_resolution_confidence_threshold, 0.81)
        self.assertEqual(policy.workflow_understanding.metadata_filter_confidence_threshold, 0.93)
        self.assertEqual(policy.memory_retrieval.prompt_limit, 7)
        self.assertEqual(policy.memory_retrieval.state_limit, 6)
        self.assertEqual(policy.memory_retrieval.rag_limit, 5)
        self.assertEqual(policy.memory_retrieval.tool_limit, 4)
        self.assertEqual(policy.memory_retrieval.token_budget, 900)
        self.assertEqual(policy.memory_injection.prompt_limit, 8)
        self.assertEqual(policy.memory_injection.state_limit, 9)
        self.assertEqual(policy.memory_injection.tool_limit, 6)
        self.assertEqual(policy.memory_injection.rag_limit, 7)
        self.assertEqual(policy.memory_injection.token_budget, 1000)
        self.assertEqual(policy.memory_governance.low_confidence_threshold, 0.22)
        self.assertEqual(policy.memory_governance.low_stability_threshold, 0.33)
        self.assertEqual(policy.memory_conflict.supersede_margin, 0.12)
        self.assertEqual(policy.memory_conflict.merge_similarity_threshold, 0.77)
        self.assertEqual(policy.memory_promotion.preference_promote_count, 4)
        self.assertEqual(policy.consolidation.minimum_duplicate_group_size, 3)
        self.assertEqual(policy.consolidation.max_conflicts, 4)
        self.assertEqual(policy.consolidation.confirmed_explicitness, 1.25)
        self.assertEqual(policy.consolidation.inferred_explicitness, 0.25)
        self.assertEqual(policy.consolidation.recency_window_seconds, 604800)
        self.assertEqual(policy.orchestrator.confirmed_confidence_threshold, 0.91)

    def test_settings_default_retrieval_budget_matches_expected_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(settings_module, "_load_env_file_values", return_value={}):
            settings = Settings()
            policy = settings.policy_settings()

        self.assertEqual(settings.low_score_threshold, 0.55)
        self.assertEqual(settings.dense_top_k, 10)
        self.assertEqual(settings.sparse_top_k, 8)
        self.assertEqual(settings.metadata_top_k, 8)
        self.assertEqual(settings.fusion_top_k, 15)
        self.assertEqual(settings.rerank_top_k, 8)
        self.assertEqual(settings.evidence_top_n, 5)
        self.assertEqual(policy.evidence_governance.low_score_threshold, 0.55)
        self.assertEqual(policy.hybrid_retriever.dense_top_k, 10)
        self.assertEqual(policy.hybrid_retriever.sparse_top_k, 8)
        self.assertEqual(policy.hybrid_retriever.metadata_top_k, 8)
        self.assertEqual(policy.hybrid_retriever.fusion_top_k, 15)
        self.assertEqual(policy.hybrid_retriever.rerank_top_k, 8)

    def test_settings_exposes_architecture_flags(self) -> None:
        env = {
            "LEARNING_AGENT_ENABLE_TRACE_HARNESS": "true",
            "LEARNING_AGENT_ENABLE_REPLAY_HARNESS": "true",
            "LEARNING_AGENT_ENABLE_TOOL_MOCK_HARNESS": "true",
            "LEARNING_AGENT_ENABLE_RAG_GOLDEN_EVIDENCE_HARNESS": "true",
            "LEARNING_AGENT_ENABLE_EVALUATION_HARNESS": "true",
            "LEARNING_AGENT_ENABLE_REQUIRED_FACETS_TO_PLANS": "false",
            "LEARNING_AGENT_ENABLE_PARTIAL_GROUNDED": "false",
            "LEARNING_AGENT_ENABLE_SLOT_CLARIFY": "false",
            "LEARNING_AGENT_ENABLE_RAG_PLUS_TOOL_PARTIAL_ANSWER": "false",
            "LEARNING_AGENT_ENABLE_TASK_PLAN_FOR_LOCAL_LIFE": "false",
            "LEARNING_AGENT_ENABLE_ANSWER_VERIFIER": "false",
            "LEARNING_AGENT_ANSWER_VERIFIER_MODE": "enforce",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()

        self.assertTrue(settings.enable_trace_harness)
        self.assertTrue(settings.enable_replay_harness)
        self.assertTrue(settings.enable_tool_mock_harness)
        self.assertTrue(settings.enable_rag_golden_evidence_harness)
        self.assertTrue(settings.enable_evaluation_harness)
        self.assertFalse(settings.enable_required_facets_to_plans)
        self.assertFalse(settings.enable_partial_grounded)
        self.assertFalse(settings.enable_slot_clarify)
        self.assertFalse(settings.enable_rag_plus_tool_partial_answer)
        self.assertFalse(settings.enable_task_plan_for_local_life)
        self.assertFalse(settings.enable_answer_verifier)
        self.assertEqual(settings.answer_verifier_mode, "enforce")

    def test_clarification_guard_uses_configured_thresholds(self) -> None:
        decision = evaluate_clarification(
            intent_confidence=0.61,
            reference_confidence=0.4,
            intent=IntentType.FOLLOW_UP,
            intent_threshold=0.6,
            reference_threshold=0.5,
        )
        self.assertTrue(decision.should_clarify)
        self.assertEqual(decision.reason, "low_reference_confidence")

    def test_memory_mutation_guard_blocks_deleted_records(self) -> None:
        decision = validate_memory_record_mutation(self._build_record(status=MemoryStatus.DELETED))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "reject_deleted_record")

    def test_memory_governance_policy_respects_threshold_config(self) -> None:
        policy = MemoryGovernancePolicy(
            config=MemoryGovernancePolicyConfig(low_confidence_threshold=0.8, low_stability_threshold=0.95)
        )
        candidate = self._build_candidate(confidence=0.7, stability=0.99)
        governed = policy.evaluate(candidate)
        self.assertEqual(governed.governance_action, "reject")
        self.assertFalse(governed.should_promote)

    def test_memory_conflict_resolver_respects_supersede_margin(self) -> None:
        resolver = MemoryConflictResolver(
            config=MemoryConflictPolicyConfig(supersede_margin=0.1, merge_similarity_threshold=0.9)
        )
        incoming = self._build_record(confidence=0.7).model_copy(update={"summary": "incoming"})
        existing = self._build_record(confidence=0.65).model_copy(update={"memory_id": "existing", "summary": "existing"})

        result = resolver.resolve(incoming, [existing])
        self.assertEqual(result.strategy.value, "KEEP_BOTH")

    def test_promotion_policy_promotes_preference_at_threshold(self) -> None:
        promotion_policy = MemoryPromotionPolicy(config=PromotionConfig(preference_promote_count=2))
        payload = MemoryPromotionInput(
            session_id="session-1",
            turn_id="turn-1",
            user_id="user-1",
            query="请继续讲解这个主题",
            answer_text="好的。",
            resolved_topic="policy",
            output_style="concise",
            explicit_signals=ExplicitUserSignals(),
            current_session=PersistentSessionContext(current_topic="policy"),
            current_preferences=UserPreferenceProfile(user_id="user-1", answer_style_counter={"concise": 1}),
            current_time=datetime.now(timezone.utc),
        )
        promoted = promotion_policy.evaluate(payload)
        self.assertTrue(promoted.semantic_facts)
        self.assertEqual(promoted.preference_patch["answer_style_counter"]["concise"], 2)
        self.assertEqual(promoted.preference_patch["preferred_output_style"], "concise")
        self.assertIn("promoted_output_style", promoted.reasons)

    def _build_candidate(self, *, confidence: float, stability: float) -> MemoryCandidate:
        return MemoryCandidate(
            candidate_id="candidate-1",
            should_promote=True,
            memory_type=MemoryType.SEMANTIC,
            target_store=MemoryTargetStore.POSTGRES,
            confidence=confidence,
            importance=0.8,
            stability=stability,
            reason="test",
            source_turn_id="turn-1",
            record=self._build_record(confidence=confidence, stability=stability),
        )


if __name__ == "__main__":
    unittest.main()
