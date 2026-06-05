from __future__ import annotations

from dataclasses import dataclass

from learning_agent_service.memory.conflict import MemoryConflictPolicyConfig
from learning_agent_service.memory.consolidation import ConsolidationPolicyConfig
from learning_agent_service.memory.governance import MemoryGovernancePolicyConfig
from learning_agent_service.memory.injection import MemoryInjectionPolicyConfig
from learning_agent_service.memory.orchestrator import MemoryOrchestratorPolicyConfig
from learning_agent_service.memory.promotion import PromotionConfig
from learning_agent_service.memory.retrieval import RetrievalPolicyConfig
from learning_agent_service.rag.evidence import EvidenceGovernanceConfig
from learning_agent_service.rag.hybrid import HybridRetrieverConfig
from learning_agent_service.rag.retrieval import RRFConfig
from learning_agent_service.rag.rewrite import QueryRewriteConfig


@dataclass(frozen=True)
class WorkflowUnderstandingPolicyConfig:
    intent_confidence_threshold: float = 0.5
    reference_resolution_confidence_threshold: float = 0.5
    metadata_filter_confidence_threshold: float = 0.5


@dataclass(frozen=True)
class PolicySettings:
    workflow_understanding: WorkflowUnderstandingPolicyConfig
    memory_retrieval: RetrievalPolicyConfig
    memory_injection: MemoryInjectionPolicyConfig
    memory_governance: MemoryGovernancePolicyConfig
    memory_conflict: MemoryConflictPolicyConfig
    memory_promotion: PromotionConfig
    consolidation: ConsolidationPolicyConfig
    orchestrator: MemoryOrchestratorPolicyConfig
    evidence_governance: EvidenceGovernanceConfig
    hybrid_retriever: HybridRetrieverConfig
    rrf: RRFConfig
    query_rewrite: QueryRewriteConfig


__all__ = [
    "ConsolidationPolicyConfig",
    "MemoryOrchestratorPolicyConfig",
    "PolicySettings",
    "WorkflowUnderstandingPolicyConfig",
]
