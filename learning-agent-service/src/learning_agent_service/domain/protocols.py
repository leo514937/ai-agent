from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from .contracts import (
    AnswerComposeRequest,
    AnswerComposeResult,
    Citation,
    CitationBuildRequest,
    ErrorPayload,
    EvidenceEvaluationRequest,
    EvidencePack,
    FastDecision,
    FinalPayload,
    GraphRuntimeMeta,
    HybridRecallResult,
    HybridRetrieveRequest,
    NormalizedToolResult,
    PersistentSessionContext,
    PersistSessionCommand,
    PersistSessionResult,
    QueryRewriteRequest,
    ReferenceResolutionRequest,
    ReferenceResolutionResult,
    RetrievalPlan,
    SseEnvelope,
    ToolExecutionCommand,
    ToolExecutionResult,
    ToolNormalizationRequest,
    ToolPlanningRequest,
    ToolSelection,
    TurnUnderstandingRequest,
)

if TYPE_CHECKING:
    from learning_agent_service.application.rag_gate import (
        RagGateDecision,
        RagGateRequest,
        RagGateVote,
    )


class ModelGatewayPort(Protocol):
    def classify_turn(self, request: TurnUnderstandingRequest) -> FastDecision:
        ...


class SessionContextPort(Protocol):
    def load(self, session_id: str, user_id: str) -> PersistentSessionContext:
        ...

    def save(self, context: PersistentSessionContext, runtime: GraphRuntimeMeta) -> None:
        ...

    def load_any(self, session_id: str) -> PersistentSessionContext:
        ...


class RAGOrchestratorPort(Protocol):
    def resolve_reference(self, request: ReferenceResolutionRequest) -> ReferenceResolutionResult:
        ...

    def rewrite_query(self, request: QueryRewriteRequest) -> RetrievalPlan:
        ...

    def hybrid_retrieve(self, request: HybridRetrieveRequest) -> HybridRecallResult:
        ...

    def evaluate_evidence(self, request: EvidenceEvaluationRequest) -> EvidencePack:
        ...

    def build_citations(self, request: CitationBuildRequest) -> Iterable[Citation]:
        ...


class RagRouteGatePort(Protocol):
    def precheck(self, request: RagGateRequest) -> RagGateVote:
        ...

    def should_skip_memory_retrieval(self, request: RagGateRequest) -> bool:
        ...

    def decide(self, request: RagGateRequest) -> RagGateDecision:
        ...


class MemoryServicePort(Protocol):
    def persist_session(self, command: PersistSessionCommand) -> PersistSessionResult:
        ...

    def load_any(self, session_id: str) -> PersistentSessionContext:
        ...


class ToolPlannerPort(Protocol):
    def plan(self, request: ToolPlanningRequest) -> ToolSelection | None:
        ...

    def plan_from_name(self, tool_name: str, input_payload: dict) -> ToolSelection:
        ...


class ToolExecutorPort(Protocol):
    def execute(self, command: ToolExecutionCommand) -> ToolExecutionResult:
        ...


class ToolResultNormalizerPort(Protocol):
    def normalize(self, request: ToolNormalizationRequest) -> NormalizedToolResult:
        ...


class AnswerComposerPort(Protocol):
    def compose(self, request: AnswerComposeRequest) -> AnswerComposeResult:
        ...


class FinalizerPort(Protocol):
    def finalize(
        self,
        *,
        terminal_event: str,
        payload: FinalPayload | ErrorPayload | dict,
        runtime: GraphRuntimeMeta,
    ) -> SseEnvelope | None:
        ...
