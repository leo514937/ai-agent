from __future__ import annotations

import logging
import json
import hashlib
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from learning_agent_service.config import Settings, get_settings
from learning_agent_service.domain import (
    ChatTurnCommand,
    FastDecision,
    KnowledgeSearchRequest,
    ReferenceResolutionResult,
    RetrievalPlan,
    TurnUnderstandingRequest,
    TurnUnderstandingResult,
)
from learning_agent_service.domain.contracts import SseEnvelope
from learning_agent_service.domain.enums import IntentType, OutputStyle
from learning_agent_service.domain.protocols import (
    AnswerComposerPort,
    FinalizerPort,
    MemoryServicePort,
    ModelGatewayPort,
    RAGOrchestratorPort,
    RagRouteGatePort,
    SessionContextPort,
    ToolExecutorPort,
    ToolPlannerPort,
    ToolResultNormalizerPort,
)
from learning_agent_service.infrastructure.db.factories import InfrastructureClients, build_infrastructure_clients
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime
from learning_agent_service.infrastructure.db.qdrant import QdrantRuntime
from learning_agent_service.infrastructure.repositories import (
    AdapterStatus,
    DurablePreferenceStore,
    DurableProfileProjectionStore,
    NoOpSemanticMemoryStore,
    MemoryOutboxRepository,
    OutboxAsyncLogStore,
    OutboxRepository,
    RedisSessionContextStore,
    RuntimeComponentMode,
    RuntimeDependencyStatus,
    RuntimeProfile,
    UserPreferenceRepository,
    UserProfileProjectionRepository,
)
from learning_agent_service.infrastructure.repositories.memory_trace_repository import MemoryTraceRepository
from learning_agent_service.infrastructure.memory import (
    DurableLongTermMemoryStore,
    DurableSemanticMemoryStore,
    LongTermMemoryRepository,
    QdrantLongTermMemoryIndex,
)
from learning_agent_service.infrastructure.repositories.in_memory import (
    InMemoryAsyncLogStore,
    InMemorySessionContextStore,
)
from learning_agent_service.memory.service import MemoryService
from learning_agent_service.memory.orchestrator import MemoryOrchestrator
from learning_agent_service.memory import (
    MemoryConsolidationJob,
    MemoryConflictResolver,
    MemoryGovernancePolicy,
    MemoryInjectionPolicy,
    MemoryPromotionPolicy,
    MemoryRetrievalPolicy,
)
from learning_agent_service.memory.stores import InMemoryLongTermMemoryStore
from learning_agent_service.rag.models import KnowledgeChunk
from learning_agent_service.rag.heuristics import HeuristicModelGateway
from learning_agent_service.rag.heuristics import HeuristicIntentGate
from learning_agent_service.rag.retrieval import (
    CrossEncoderReranker,
    HeuristicDenseRetriever,
    HeuristicMetadataRetriever,
    HeuristicReranker,
    HeuristicSparseRetriever,
    LocalBM25SparseRetriever,
    ParentChildResolver,
    QdrantFilterBuilder,
    QdrantMetadataRetriever,
    QdrantOnlineDenseRetriever,
    RemoteCrossEncoderReranker,
    RemoteReranker,
)
from learning_agent_service.rag.rewrite import QueryRewriteService
from learning_agent_service.rag.service import DEFAULT_KNOWLEDGE_CHUNKS, HybridRAGOrchestrator
from learning_agent_service.rag.local_life_retrieval import LocalLifeParentChildRetriever
from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.local_life.assistant import LocalLifeModelAssistant
from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.application.rag_gate import RagGateRequest, RagGateVote, RagRouteGate
from learning_agent_service.tools.service import (
    AnswerComposer,
    Finalizer,
    ToolExecutor,
    ToolPlanner,
    ToolResultNormalizer,
)

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except Exception:  # pragma: no cover - optional dependency path
    SqliteSaver = None

_SPARSE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepositoryBundle:
    outbox: Optional[OutboxRepository] = None
    memory_outbox: Optional[MemoryOutboxRepository] = None
    preferences: Optional[UserPreferenceRepository] = None
    profile_projection: Optional[UserProfileProjectionRepository] = None
    memory_traces: Optional[MemoryTraceRepository] = None


@dataclass
class OpenAIEmbeddingAdapter:
    runtime: OpenAIRuntime
    model: str
    embedding_model_version: str = ""
    redis_runtime: Any | None = None
    cache_ttl_seconds: int = 0

    def embed_with_stats(self, text: str) -> tuple[list[float], bool]:
        normalized_text = _normalize_embedding_query(text)
        cache_key = self._embedding_cache_key(normalized_text)
        if cache_key is not None and self.redis_runtime is not None:
            cached = self._redis_get(cache_key)
            if cached:
                try:
                    vector = json.loads(cached)
                    if isinstance(vector, list):
                        return [float(item) for item in vector], True
                except Exception:
                    _LOGGER.debug("embedding_cache_decode_failed key=%s", cache_key, exc_info=True)

        client = self.runtime.client
        embeddings = getattr(client, "embeddings", None)
        if embeddings is None or not hasattr(embeddings, "create"):
            raise RuntimeError("OpenAI runtime does not expose embeddings API")
        response = embeddings.create(model=self.model or self.runtime.default_model, input=text)
        data = getattr(response, "data", None) or []
        if not data:
            raise RuntimeError("OpenAI embeddings API returned no vectors")
        vector = getattr(data[0], "embedding", None)
        if vector is None:
            raise RuntimeError("OpenAI embeddings API returned an empty embedding")
        result = list(vector)
        if cache_key is not None and self.redis_runtime is not None and self.cache_ttl_seconds > 0:
            self._redis_set(cache_key, json.dumps(result, separators=(",", ":")))
        return result, False

    def embed(self, text: str) -> list[float]:
        vector, _cache_hit = self.embed_with_stats(text)
        return vector

    def _embedding_cache_key(self, normalized_text: str) -> str | None:
        if self.redis_runtime is None:
            return None
        query = normalized_text.strip()
        if not query:
            return None
        model_name = str(self.model or self.runtime.default_model or "").strip()
        if not model_name:
            return None
        normalized_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        keys = getattr(self.redis_runtime, "keys", None)
        if keys is not None and hasattr(keys, "embedding_cache"):
            return keys.embedding_cache(model_name, self.embedding_model_version or "v1", normalized_hash)
        prefix = getattr(self.redis_runtime, "prefix", "learn-agent")
        return f"{prefix}:embedding:{model_name}:{self.embedding_model_version or 'v1'}:{normalized_hash}"

    def _redis_get(self, cache_key: str) -> str | None:
        client = getattr(self.redis_runtime, "client", None)
        if client is None:
            return None
        getter = getattr(client, "get", None)
        if not callable(getter):
            return None
        try:
            value = getter(cache_key)
        except Exception:
            _LOGGER.debug("embedding_cache_get_failed key=%s", cache_key, exc_info=True)
            return None
        return str(value) if value not in (None, "") else None

    def _redis_set(self, cache_key: str, payload: str) -> None:
        client = getattr(self.redis_runtime, "client", None)
        if client is None:
            return
        setter = getattr(client, "setex", None)
        try:
            if callable(setter):
                setter(cache_key, int(self.cache_ttl_seconds), payload)
                return
            set_fn = getattr(client, "set", None)
            if callable(set_fn):
                set_fn(cache_key, payload, ex=int(self.cache_ttl_seconds))
        except Exception:
            _LOGGER.debug("embedding_cache_set_failed key=%s", cache_key, exc_info=True)


def _resolve_memory_vector_size(settings: Settings, adapter: OpenAIEmbeddingAdapter | None = None) -> int:
    configured_size = settings.qdrant.memory_vector_size
    if configured_size is not None:
        return int(configured_size)
    if adapter is not None:
        try:
            vector = adapter.embed("probe")
            size = len(vector)
            settings.qdrant.memory_vector_size = size
            return size
        except Exception as e:
            raise RuntimeError(
                f"Failed to resolve memory_vector_size via embedding probe: {e}"
            ) from e
    raise RuntimeError(
        "Qdrant memory_vector_size is not configured; durable memory requires an explicit vector size"
    )


def _build_memory_embedding_adapter(settings: Settings, infra: InfrastructureClients) -> OpenAIEmbeddingAdapter:
    provider = str(getattr(settings.embedding, "memory_provider", "") or "").strip().lower()
    if provider not in {"openai"}:
        raise RuntimeError(f"Unsupported memory embedding provider: {provider or 'unknown'}")
    if infra.openai is None:
        raise RuntimeError("OpenAI runtime is required for durable memory embedding")
    return _build_openai_embedding_adapter(
        runtime=infra.openai,
        model=settings.embedding.memory_model,
        embedding_model_version=getattr(settings.openai, "embedding_model_version", "") or "",
        redis_runtime=infra.redis,
        cache_ttl_seconds=getattr(settings.redis, "embedding_cache_ttl_seconds", 0) or 0,
    )


def _build_openai_embedding_adapter(
    *,
    runtime: OpenAIRuntime,
    model: str,
    embedding_model_version: str = "",
    redis_runtime: Any | None = None,
    cache_ttl_seconds: int = 0,
) -> OpenAIEmbeddingAdapter:
    return OpenAIEmbeddingAdapter(
        runtime=runtime,
        model=model,
        embedding_model_version=embedding_model_version,
        redis_runtime=redis_runtime,
        cache_ttl_seconds=int(cache_ttl_seconds or 0),
    )


@dataclass(frozen=True)
class OpenAIQueryRewriteAdapter:
    runtime: OpenAIRuntime
    model: str
    temperature: float = 0.0

    def __call__(self, context, base_plan, fallback_reason: str) -> Mapping[str, Any]:
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise RuntimeError("OpenAI runtime does not expose Responses API")

        prompt = {
            "raw_query": context.raw_query,
            "resolved_topic": context.resolved_topic,
            "session_topic": context.session_topic,
            "intent": context.intent,
            "requested_output_style": context.requested_output_style,
            "intent_confidence": context.intent_confidence,
            "fallback_reason": fallback_reason,
            "semantic_query": base_plan.semantic_query,
            "keyword_query": base_plan.keyword_query,
            "retrieval_filters": base_plan.retrieval_filters.as_dict(),
            "user_preferences": dict(context.user_preferences),
        }
        response = responses.create(
            model=self.model or self.runtime.default_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You rewrite retrieval queries for a hybrid RAG system. "
                                "Return strict JSON with keys: semantic_query, keyword_query, rewritten_queries, step_back_query, retrieval_filters, filter_confidence."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=300,
        )
        return json.loads(_extract_response_text(response))


@dataclass(frozen=True)
class OpenAIHyDEAdapter:
    runtime: OpenAIRuntime
    model: str
    temperature: float = 0.0

    def __call__(self, context, base_plan, trigger_reason: str) -> Mapping[str, Any]:
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise RuntimeError("OpenAI runtime does not expose Responses API")

        prompt = {
            "raw_query": context.raw_query,
            "resolved_topic": context.resolved_topic,
            "session_topic": context.session_topic,
            "intent": context.intent,
            "requested_output_style": context.requested_output_style,
            "intent_confidence": context.intent_confidence,
            "trigger_reason": trigger_reason,
            "semantic_query": base_plan.semantic_query,
            "keyword_query": base_plan.keyword_query,
            "retrieval_filters": base_plan.retrieval_filters.as_dict(),
            "user_preferences": dict(context.user_preferences),
        }
        response = responses.create(
            model=self.model or self.runtime.default_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You generate a concise hypothetical passage to improve sparse retrieval. "
                                "Return strict JSON with keys: hyde_passage, hyde_title, hyde_keywords."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=220,
        )
        return json.loads(_extract_response_text(response))


@dataclass(frozen=True)
class OpenAIAnswerComposeAdapter:
    runtime: OpenAIRuntime
    model: str
    temperature: float = 0.0

    def __call__(self, request: AnswerComposeRequest) -> str:
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise RuntimeError("OpenAI runtime does not expose Responses API")

        rag_result = request.rag_result
        evidence_pack = rag_result.evidence_pack if rag_result else None
        evidence_items = []
        if evidence_pack is not None:
            for item in evidence_pack.items[:5]:
                evidence_items.append(
                    {
                        "chunk_id": item.chunk_id,
                        "content": item.content,
                        "score": item.score,
                        "tier": item.tier,
                        "citation_chunk_id": item.citation_chunk_id,
                        "source_chunk_id": item.source_chunk_id,
                        "parent_chunk_id": item.parent_chunk_id,
                        "metadata": dict(item.metadata),
                    }
                )
        prompt = {
            "raw_query": request.raw_query,
            "requested_output_style": request.requested_output_style.value if request.requested_output_style else None,
            "evidence_status": getattr(evidence_pack, "evidence_status", getattr(rag_result, "evidence_status", "EMPTY")) if rag_result else "EMPTY",
            "evidence_items": evidence_items,
            "citations": [c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c) for c in (rag_result.citations if rag_result else [])],
            "plan_summary": request.plan_summary.model_dump(mode="json") if request.plan_summary else None,
            "tool_result": request.tool_result.model_dump(mode="json") if request.tool_result else None,
            "memory_injection_plan": request.memory_injection_plan.model_dump(mode="json") if request.memory_injection_plan else None,
            "history_summary": request.history_summary,
        }
        stream_sink = request.stream_event_sink
        stream_meta = dict(request.stream_event_meta or {})
        started_at = time.perf_counter()
        answer_parts: list[str] = []
        thinking_parts: list[str] = ["<details><summary>思考</summary>\n"]
        details_closed = False
        with responses.stream(
            model=self.model or self.runtime.default_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a helpful answer composer for a hybrid assistant. "
                                "If evidence_status is OK, answer only from the provided evidence and citations. "
                                "If evidence_status is EMPTY or WEAK and no tool result is present, answer the user's question naturally and concisely using general reasoning, "
                                "and ask for missing details in plain text when the request is incomplete. "
                                "If the user asks about past conversations or memory, please refer to the 'history_summary' provided in the prompt. "
                                "Never emit cards, JSON, or structured UI instructions. "
                                "Return only the final answer text."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=500,
        ) as stream:
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type not in ("response.output_text.delta", "response.reasoning_text.delta"):
                    continue

                delta = str(getattr(event, "delta", "") or "")
                if not delta:
                    continue

                if event_type == "response.reasoning_text.delta":
                    thinking_parts.append(delta)
                    
                    # 组合实时内容：当前思考块（已打开 details） + 已经产生的回答（若有）
                    current_thinking = "".join(thinking_parts)
                    current_answer = current_thinking
                    if answer_parts and not details_closed:
                        current_answer += "\n</details>\n\n"
                    if answer_parts:
                        current_answer += "".join(answer_parts)
                    
                    self._emit_stream_delta(
                        stream_sink=stream_sink,
                        meta=stream_meta,
                        delta=delta,
                        answer_text=current_answer,
                    )
                else:  # event_type == "response.output_text.delta"
                    if not details_closed:
                        # 思考结束，彻底且永久闭合前置 details 标签
                        details_closed = True
                        thinking_parts.append("\n</details>\n\n")
                    
                    answer_parts.append(delta)
                    
                    # 组合最终实时内容：完全闭合的思考文本 + 回答正文
                    current_answer = "".join(thinking_parts) + "".join(answer_parts)
                    self._emit_stream_delta(
                        stream_sink=stream_sink,
                        meta=stream_meta,
                        delta=delta,
                        answer_text=current_answer,
                    )

            try:
                response = stream.get_final_response()
                final_text = str(getattr(response, "output_text", "") or "").strip()
            except Exception:
                final_text = ""

        # 如果 stream 结束，且 details_closed 仍为 False，要彻底闭合它
        if not details_closed:
            details_closed = True
            thinking_parts.append("\n</details>\n\n")

        # 确保如果有思考内容，要把思考内容和正文内容合并作为最终返回文本
        combined_final = "".join(thinking_parts) + "".join(answer_parts)
        if not final_text:
            final_text = combined_final.strip()
        else:
            # 如果大模型正常返回了 final_text，它是 output_text，我们需要在前面拼上已经彻底闭合的思考流
            thinking_prefix = "".join(thinking_parts).strip()
            if thinking_prefix:
                final_text = thinking_prefix + "\n\n" + final_text

        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "openai_answer_compose_timing elapsed_ms=%.1f model=%s evidence_items=%s",
            elapsed_ms,
            self.model or self.runtime.default_model,
            len(evidence_items),
        )
        return final_text

    def _emit_stream_delta(
        self,
        *,
        stream_sink: Any,
        meta: Mapping[str, Any],
        delta: str,
        answer_text: str,
    ) -> None:
        if stream_sink is None:
            return

        envelope = SseEnvelope(
            event_type="delta",
            trace_id=str(meta.get("trace_id") or ""),
            session_id=str(meta.get("session_id") or ""),
            turn_id=str(meta.get("turn_id") or ""),
            timestamp=datetime.now(timezone.utc),
            workflow_version=str(meta.get("workflow_version") or "learn-agent/v1"),
            payload={
                "delta": delta,
                "answer_text": answer_text,
                "current_stage": str(meta.get("current_stage") or "compose"),
                "stage_status": str(meta.get("stage_status") or "streaming"),
                "route_decision": meta.get("route_decision"),
                "route_reason": meta.get("route_reason"),
            },
        )
        if callable(stream_sink):
            stream_sink(envelope)
            return
        put = getattr(stream_sink, "put", None)
        if callable(put):
            put(envelope)


@dataclass(frozen=True)
class UnderstandingDeps:
    model_gateway: ModelGatewayPort
    status: AdapterStatus


@dataclass(frozen=True)
class RagDeps:
    rag_orchestrator: RAGOrchestratorPort
    status: AdapterStatus


@dataclass(frozen=True)
class RagGateDeps:
    rag_route_gate: RagRouteGatePort
    status: AdapterStatus


@dataclass(frozen=True)
class MemoryDeps:
    session_context_store: SessionContextPort
    async_log_store: object
    memory_service: MemoryServicePort
    memory_orchestrator: MemoryOrchestrator
    long_term_store: object | None = None
    trace_repository: object | None = None
    preference_store: object | None = None
    profile_projection_store: object | None = None
    semantic_memory_store: object | None = None
    statuses: tuple[AdapterStatus, ...] = ()


@dataclass(frozen=True)
class ToolDeps:
    planner: ToolPlannerPort
    executor: ToolExecutorPort
    result_normalizer: ToolResultNormalizerPort


@dataclass(frozen=True)
class StreamingDeps:
    answer_composer: AnswerComposerPort
    finalizer: FinalizerPort


@dataclass
class ApplicationRuntime:
    settings: Settings
    infrastructure_clients: InfrastructureClients
    repositories: RepositoryBundle
    runtime_dependency_status: RuntimeDependencyStatus
    runtime_profile: RuntimeProfile
    workflow_checkpointer: object | None
    understanding: UnderstandingDeps
    rag: RagDeps
    rag_gate: RagGateDeps
    memory: MemoryDeps
    tools: ToolDeps
    streaming: StreamingDeps
    java_business_client: Any | None = None
    local_life_assistant: Any | None = None

    @property
    def session_context_store(self) -> SessionContextPort:
        return self.memory.session_context_store

    def async_log_store(self) -> object:
        return self.memory.async_log_store

    @property
    def model_gateway(self) -> ModelGatewayPort:
        return self.understanding.model_gateway

    @property
    def rag_orchestrator(self) -> RAGOrchestratorPort:
        return self.rag.rag_orchestrator

    @property
    def rag_route_gate(self) -> RagRouteGatePort:
        return self.rag_gate.rag_route_gate

    @property
    def memory_service(self) -> MemoryServicePort:
        return self.memory.memory_service

    @property
    def memory_orchestrator(self) -> MemoryOrchestrator:
        return self.memory.memory_orchestrator

    @property
    def long_term_store(self) -> object | None:
        return self.memory.long_term_store

    @property
    def trace_repository(self) -> object | None:
        return self.memory.trace_repository

    @property
    def memory_trace_repository(self) -> object | None:
        return self.memory.trace_repository

    @property
    def outbox_repository(self) -> OutboxRepository | None:
        return self.repositories.outbox

    @property
    def long_term_repository(self) -> object | None:
        store = self.memory.long_term_store
        return getattr(store, "repository", None) if store is not None else None

    @property
    def tool_planner(self) -> ToolPlannerPort:
        return self.tools.planner

    @property
    def tool_executor(self) -> ToolExecutorPort:
        return self.tools.executor

    @property
    def tool_result_normalizer(self) -> ToolResultNormalizerPort:
        return self.tools.result_normalizer

    @property
    def answer_composer(self) -> AnswerComposerPort:
        return self.streaming.answer_composer

    @property
    def finalizer(self) -> FinalizerPort:
        return self.streaming.finalizer

@dataclass(frozen=True)
class AppDependencies:
    runtime: ApplicationRuntime

    @property
    def container(self) -> ApplicationRuntime:
        return self.runtime


@dataclass
class OpenAIBackedModelGateway:
    runtime: OpenAIRuntime
    fallback: ModelGatewayPort
    intent_gate: HeuristicIntentGate | None = None
    last_degrade_to: str | None = None

    def classify_turn(self, request: TurnUnderstandingRequest) -> FastDecision:
        self.last_degrade_to = None
        gate = self.intent_gate or HeuristicIntentGate()
        fast_decision = gate.fast_decide(request)
        if fast_decision is not None:
            return fast_decision

        timeout_seconds = 1.2
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="intent-classify") as executor:
            future = executor.submit(self._classify_with_openai, request.command)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                self.last_degrade_to = "classify_timeout_fallback"
                _LOGGER.warning(
                    "openai_turn_classify_timeout timeout_ms=%.0f model=%s message_chars=%s",
                    timeout_seconds * 1000.0,
                    self.runtime.default_model,
                    len(request.command.message or ""),
                )
                return gate.fallback_decide(request)
            except Exception:
                self.last_degrade_to = "classify_error_fallback"
                return gate.fallback_decide(request)

    def _classify_with_openai(self, command: ChatTurnCommand) -> FastDecision:
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise RuntimeError("OpenAI runtime does not expose Responses API")

        prompt = {
            "message": command.message,
            "topic_hint": command.topic_hint,
            "response_mode": str(command.response_mode) if command.response_mode else None,
            "history_summary": command.history_summary,
            "client_context": command.client_context,
            "output_contract": {
                "intent": "string enum",
                "needs_rag": "boolean",
                "needs_tool": "boolean",
                "needs_clarify": "boolean",
                "needs_query_rewrite": "boolean",
                "confidence": "number",
                "key_slots": "object",
            },
        }
        started_at = time.perf_counter()
        response = responses.create(
            model=self.runtime.default_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You classify a chat turn using a compact schema. "
                                "Return strict JSON with keys: intent, needs_rag, needs_tool, needs_clarify, needs_query_rewrite, confidence, key_slots. "
                                "Do not return reference_resolution, retrieval_plan, tool_plan, answer_plan, or other expanded planning objects. "
                                "Prefer a small, direct decision. "
                                "For local-life related turns, key_slots may include domain, local_life_intent, tool_name, tool_input, city, shop_name, and query. "
                                "For greetings, thanks, profile questions, and other direct-response turns, set needs_rag=false and needs_tool=false."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                },
            ],
            temperature=0,
            max_output_tokens=200,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "openai_turn_classify_timing elapsed_ms=%.1f model=%s message_chars=%s",
            elapsed_ms,
            self.runtime.default_model,
            len(command.message or ""),
        )
        payload = json.loads(_extract_response_text(response))
        intent = _safe_intent(payload.get("intent"))
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        needs_rag = bool(payload.get("needs_rag", False))
        needs_tool = bool(payload.get("needs_tool", False))
        needs_clarify = bool(payload.get("needs_clarify", False))
        needs_query_rewrite = bool(payload.get("needs_query_rewrite", False))
        key_slots = payload.get("key_slots", {})
        if not isinstance(key_slots, dict):
            key_slots = {}
        key_slots = _enrich_local_life_slots(intent.value if intent is not None else None, key_slots, command)
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        extra = {
            **dict(extra),
            "route_candidate": extra.get("route_candidate") or payload.get("route_candidate"),
            "route_candidates": extra.get("route_candidates") or payload.get("route_candidates") or [],
            "fast_classify": True,
        }
        return FastDecision(
            intent=intent,
            needs_rag=needs_rag,
            needs_tool=needs_tool,
            needs_clarify=needs_clarify,
            needs_query_rewrite=needs_query_rewrite,
            confidence=max(0.0, min(confidence, 1.0)),
            key_slots=key_slots,
            extra=extra,
        )


@dataclass(frozen=True)
class OpenAIRagGateJudge:
    runtime: OpenAIRuntime
    model: str
    temperature: float = 0.0

    def __call__(self, request: RagGateRequest) -> RagGateVote:
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            raise RuntimeError("OpenAI runtime does not expose Responses API")

        prompt = {
            "raw_query": request.raw_query,
            "intent": request.intent.value if request.intent is not None else None,
            "intent_confidence": request.intent_confidence,
            "requested_output_style": request.requested_output_style.value if request.requested_output_style else None,
            "current_topic": request.current_topic,
            "recent_entities": list(request.recent_entities),
            "history_summary": request.history_summary,
            "reference_confidence": request.reference_confidence,
            "reference_resolved": request.reference_resolved,
            "client_context": dict(request.client_context),
        }
        started_at = time.perf_counter()
        response = responses.create(
            model=self.model or self.runtime.default_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Decide whether a user turn should enter RAG retrieval. "
                                "Return strict JSON with keys: vote, reason, confidence, response_kind. "
                                "Use vote=allow only for contentful knowledge questions that should reach retrieval. "
                                "Use vote=deny for greetings, chitchat, empty or low-information turns. "
                                "Use vote=uncertain when you are not sure."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                },
            ],
            temperature=self.temperature,
            max_output_tokens=180,
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "openai_rag_gate_timing elapsed_ms=%.1f model=%s query_chars=%s",
            elapsed_ms,
            self.model or self.runtime.default_model,
            len(request.raw_query or ""),
        )
        payload = json.loads(_extract_response_text(response))
        vote = str(payload.get("vote") or "uncertain").strip().lower()
        if vote not in {"allow", "deny", "uncertain"}:
            vote = "uncertain"
        reason = str(payload.get("reason") or "llm_gate_response").strip()
        response_kind = str(payload.get("response_kind") or "fallback").strip().lower() or "fallback"
        try:
            confidence = float(payload.get("confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0
        return RagGateVote(
            vote=vote,
            reason=reason,
            confidence=max(0.0, min(confidence, 1.0)),
            response_kind=response_kind,
        )


def build_dependencies(settings: Settings | None = None) -> AppDependencies:
    resolved = settings or get_settings()
    infra = build_infrastructure_clients(
        settings=resolved,
        allow_partial=resolved.allow_in_memory_fallback and not resolved.is_production_like(),
    )
    repositories = _build_repository_bundle(infra)

    understanding = _build_understanding_deps(resolved, infra)
    rag = _build_rag_deps(resolved, infra)
    rag_gate = _build_rag_gate_deps(resolved, infra)
    memory = _build_memory_deps(resolved, infra, repositories)
    java_business_client, java_business_status, local_life_assistant, local_life_assistant_status = _build_local_life_adapters(
        resolved,
        infra,
    )
    local_life_retriever = _build_local_life_retriever(resolved, infra)
    local_life_query_router = _build_local_life_query_router()
    tools = _build_tool_deps(rag.rag_orchestrator, java_business_client=java_business_client)
    streaming = _build_streaming_deps(resolved, infra)
    workflow_checkpointer = _build_workflow_checkpointer(resolved)

    adapter_statuses = (
        understanding.status,
        rag.status,
        rag_gate.status,
        *memory.statuses,
        _adapter_status("postgres", infra.postgres is not None, "real"),
        _adapter_status("redis", infra.redis is not None, "real"),
        _adapter_status("qdrant", infra.qdrant is not None, "real"),
        _adapter_status("openai", infra.openai is not None, "real"),
        java_business_status,
        local_life_assistant_status,
    )
    runtime_dependency_status = RuntimeDependencyStatus(
        adapters=tuple(adapter_statuses),
        bootstrap_errors=tuple(infra.bootstrap_errors),
    )
    runtime_profile = _build_runtime_profile(resolved, runtime_dependency_status)

    runtime = ApplicationRuntime(
        settings=resolved,
        infrastructure_clients=infra,
        repositories=repositories,
        runtime_dependency_status=runtime_dependency_status,
        runtime_profile=runtime_profile,
        workflow_checkpointer=workflow_checkpointer,
        understanding=understanding,
        rag=rag,
        rag_gate=rag_gate,
        memory=memory,
        tools=tools,
        streaming=streaming,
        java_business_client=java_business_client,
        local_life_assistant=local_life_assistant,
    )
    setattr(runtime, "local_life_retriever", local_life_retriever)
    setattr(runtime, "local_life_query_router", local_life_query_router)
    return AppDependencies(runtime=runtime)


def _build_understanding_deps(
    settings: Settings,
    infra: InfrastructureClients,
) -> UnderstandingDeps:
    model_gateway, status = _build_model_gateway(settings, infra)
    return UnderstandingDeps(model_gateway=model_gateway, status=status)


def _build_rag_deps(
    settings: Settings,
    infra: InfrastructureClients,
) -> RagDeps:
    rag_orchestrator, status = _build_rag_orchestrator(settings, infra)
    return RagDeps(rag_orchestrator=rag_orchestrator, status=status)


def _build_rag_gate_deps(
    settings: Settings,
    infra: InfrastructureClients,
) -> RagGateDeps:
    gate, status = _build_rag_route_gate(settings, infra)
    return RagGateDeps(rag_route_gate=gate, status=status)


def _build_rag_route_gate(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[RagRouteGatePort, AdapterStatus]:
    fallback_gate = RagRouteGate()
    if settings.prefer_real_adapters and infra.openai is not None:
        judge = OpenAIRagGateJudge(
            runtime=infra.openai,
            model=infra.openai.default_model,
            temperature=0.0,
        )
        return (
            RagRouteGate(llm_judge=judge),
            AdapterStatus(
                name="rag_route_gate",
                mode="real",
                ready=True,
                details={
                    "backend": "openai_responses",
                    "fallback": "rule_based",
                    "model": infra.openai.default_model,
                },
            ),
        )
    return (
        fallback_gate,
        AdapterStatus(
            name="rag_route_gate",
            mode="fallback",
            ready=True,
            details={
                "backend": "rule_based",
                "reason": "openai_unavailable_or_disabled",
            },
        ),
    )


def _build_query_rewrite_service(settings: Settings, infra: InfrastructureClients) -> QueryRewriteService:
    llm_rewriter = None
    if settings.enable_llm_query_rewrite and infra.openai is not None:
        llm_rewriter = OpenAIQueryRewriteAdapter(
            runtime=infra.openai,
            model=settings.llm_query_rewrite_model or infra.openai.default_model,
            temperature=settings.llm_query_rewrite_temperature,
        )
    hyde_rewriter = None
    if settings.enable_hyde_sparse_retrieval and infra.openai is not None:
        hyde_rewriter = OpenAIHyDEAdapter(
            runtime=infra.openai,
            model=settings.hyde_sparse_retrieval_model or infra.openai.default_model,
            temperature=settings.hyde_sparse_retrieval_temperature,
        )
    policy = settings.policy_settings()
    return QueryRewriteService(policy.query_rewrite, llm_rewriter=llm_rewriter, hyde_rewriter=hyde_rewriter)


def _build_dense_retriever(
    settings: Settings,
    infra: InfrastructureClients,
    chunks: tuple[KnowledgeChunk, ...],
    parent_child_resolver: ParentChildResolver,
    filter_builder: QdrantFilterBuilder,
):
    fallback = HeuristicDenseRetriever(chunks, parent_child_resolver, filter_builder=filter_builder)
    if settings.enable_online_dense_retrieval and infra.qdrant is not None and infra.openai is not None:
        try:
            return QdrantOnlineDenseRetriever(
                client=infra.qdrant.client,
                collection_name=infra.qdrant.local_life_hybrid_collection,
                vector_name=infra.qdrant.knowledge_vector_name,
                embedding_adapter=_build_openai_embedding_adapter(
                    runtime=infra.openai,
                    model=settings.openai.embedding_model,
                    embedding_model_version=getattr(settings.openai, "embedding_model_version", "") or "",
                    redis_runtime=infra.redis,
                    cache_ttl_seconds=getattr(settings.redis, "embedding_cache_ttl_seconds", 0) or 0,
                ),
                fallback=fallback,
                enabled=True,
                filter_builder=filter_builder,
                vector_size=infra.qdrant.knowledge_vector_size,
                distance=infra.qdrant.knowledge_distance,
            )
        except RuntimeError as exc:
            _LOGGER.warning(
                "qdrant_online_dense_retriever_disabled: %s; falling back to heuristic dense retrieval",
                exc,
            )
            return fallback
    return fallback


def _build_sparse_retriever(
    settings: Settings,
    infra: InfrastructureClients,
    chunks: tuple[KnowledgeChunk, ...],
    parent_child_resolver: ParentChildResolver,
    filter_builder: QdrantFilterBuilder,
):
    fallback = HeuristicSparseRetriever(chunks, parent_child_resolver, filter_builder=filter_builder)
    bm25_retriever = LocalBM25SparseRetriever(
        chunks,
        parent_child_resolver,
        fallback=fallback,
        enabled=settings.enable_bm25_sparse_retrieval,
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        filter_builder=filter_builder,
    )
    return bm25_retriever


def _build_metadata_retriever(
    settings: Settings,
    infra: InfrastructureClients,
    chunks: tuple[KnowledgeChunk, ...],
    parent_child_resolver: ParentChildResolver,
    filter_builder: QdrantFilterBuilder,
):
    fallback = HeuristicMetadataRetriever(chunks, parent_child_resolver, filter_builder=filter_builder)
    if (settings.enable_online_dense_retrieval or settings.enable_online_sparse_retrieval) and infra.qdrant is not None and infra.openai is not None:
        try:
            return QdrantMetadataRetriever(
                client=infra.qdrant.client,
                collection_name=infra.qdrant.local_life_hybrid_collection,
                vector_name=infra.qdrant.knowledge_vector_name,
                embedding_adapter=_build_openai_embedding_adapter(
                    runtime=infra.openai,
                    model=settings.openai.embedding_model,
                    embedding_model_version=getattr(settings.openai, "embedding_model_version", "") or "",
                    redis_runtime=infra.redis,
                    cache_ttl_seconds=getattr(settings.redis, "embedding_cache_ttl_seconds", 0) or 0,
                ),
                fallback=fallback,
                enabled=True,
                filter_builder=filter_builder,
                scroll_fallback_enabled=settings.enable_online_dense_retrieval or settings.enable_online_sparse_retrieval,
                vector_size=infra.qdrant.knowledge_vector_size,
                distance=infra.qdrant.knowledge_distance,
            )
        except RuntimeError as exc:
            _LOGGER.warning(
                "qdrant_metadata_retriever_disabled: %s; falling back to heuristic metadata retrieval",
                exc,
            )
            return fallback
    return fallback


def _build_reranker(settings: Settings) -> HeuristicReranker | RemoteReranker | CrossEncoderReranker:
    fallback = HeuristicReranker()
    provider = (settings.reranker_provider or ("remote" if settings.enable_remote_reranker else "heuristic")).strip().lower()
    if provider == "remote":
        return RemoteCrossEncoderReranker(
            endpoint=settings.remote_reranker_endpoint,
            api_key=settings.remote_reranker_api_key,
            timeout_seconds=settings.remote_reranker_timeout_seconds,
            model=settings.remote_reranker_model,
            fallback=fallback,
            enabled=True,
        )
    return fallback


def _memory_fallback_allowed(settings: Settings) -> bool:
    environment = (settings.environment or settings.app.environment or "").strip().lower()
    return bool(
        settings.allow_in_memory_fallback
        and (settings.debug or environment in {"development", "dev", "local", "test", "testing", "ci"})
    )


def _build_memory_deps(
    settings: Settings,
    infra: InfrastructureClients,
    repositories: RepositoryBundle,
) -> MemoryDeps:
    policy = settings.policy_settings()
    session_context_store, session_status = _build_session_context_store(settings, infra)
    async_log_store, async_log_status = _build_async_log_store(settings, repositories)
    preference_store, preference_status = _build_preference_store(repositories)
    profile_projection_store, profile_projection_status = _build_profile_projection_store(repositories)
    durable_backend = _build_durable_memory_backend(settings, infra)
    if durable_backend is not None:
        long_term_store, semantic_memory_store, long_term_status, semantic_status = durable_backend
    else:
        long_term_store, long_term_status = _build_long_term_memory_store(settings, infra)
        semantic_memory_store, semantic_status = _build_semantic_memory_store(settings, infra)
    trace_repository = _build_memory_trace_repository(repositories)

    memory_service = MemoryService(
        session_store=session_context_store,
        async_log_store=async_log_store,
        settings=settings,
        preference_store=preference_store,
        profile_projection_store=profile_projection_store,
        semantic_memory_store=semantic_memory_store,
        promotion_policy=MemoryPromotionPolicy(
            config=policy.memory_promotion,
            governance=MemoryGovernancePolicy(config=policy.memory_governance),
        ),
    )
    memory_orchestrator = MemoryOrchestrator(
        session_store=session_context_store,
        long_term_store=long_term_store,
        profile_projection_store=profile_projection_store,
        trace_repository=trace_repository,
        retrieval_policy=MemoryRetrievalPolicy(config=policy.memory_retrieval),
        injection_policy=MemoryInjectionPolicy(config=policy.memory_injection),
        consolidation_job=MemoryConsolidationJob(config=policy.consolidation),
        promotion_policy=MemoryPromotionPolicy(
            config=policy.memory_promotion,
            governance=MemoryGovernancePolicy(config=policy.memory_governance),
        ),
        conflict_resolver=MemoryConflictResolver(config=policy.memory_conflict),
        policy=policy.orchestrator,
    )
    return MemoryDeps(
        session_context_store=session_context_store,
        async_log_store=async_log_store,
        memory_service=memory_service,
        memory_orchestrator=memory_orchestrator,
        long_term_store=long_term_store,
        trace_repository=trace_repository,
        preference_store=preference_store,
        profile_projection_store=profile_projection_store,
        semantic_memory_store=semantic_memory_store,
        statuses=(
            session_status,
            async_log_status,
            preference_status,
            profile_projection_status,
            long_term_status,
            semantic_status,
        ),
    )


def _build_memory_trace_repository(repositories: RepositoryBundle) -> Optional[MemoryTraceRepository]:
    return repositories.memory_traces


def _build_local_life_adapters(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[JavaBusinessClient, AdapterStatus, LocalLifeModelAssistant, AdapterStatus]:
    java_business_client = JavaBusinessClient(settings=settings)
    fallback_allowed = bool(settings.allow_in_memory_fallback and not settings.is_production_like())
    java_business_status = AdapterStatus(
        name="java_business_client",
        mode="real" if java_business_client.enabled else ("fallback" if fallback_allowed else "unavailable"),
        ready=java_business_client.enabled or fallback_allowed,
        details={
            "base_url": java_business_client.base_url or None,
            "fallback_enabled": java_business_client.enable_fallback,
            "source": "java" if java_business_client.enabled else ("transaction_store" if fallback_allowed else "unavailable"),
        },
    )
    assistant = LocalLifeModelAssistant(
        runtime=infra.openai,
        model=settings.llm_query_rewrite_model or settings.remote_reranker_model or "",
        temperature=float(getattr(settings, "llm_query_rewrite_temperature", 0.0) or 0.0),
    )
    assistant_status = AdapterStatus(
        name="local_life_model_assistant",
        mode="real" if assistant.enabled else ("fallback" if fallback_allowed else "unavailable"),
        ready=assistant.enabled or fallback_allowed,
        details={
            "backend": "openai_responses" if assistant.enabled else ("heuristic" if fallback_allowed else "unavailable"),
            "model": assistant.model or (infra.openai.default_model if infra.openai is not None else None),
        },
    )
    return java_business_client, java_business_status, assistant, assistant_status


def _build_local_life_retriever(settings: Settings, infra: InfrastructureClients) -> Any | None:
    if infra.qdrant is None or infra.openai is None:
        return None
    return LocalLifeParentChildRetriever(
        qdrant_client=infra.qdrant.client,
        embedding_adapter=_build_openai_embedding_adapter(
            runtime=infra.openai,
            model=settings.openai.embedding_model,
            embedding_model_version=getattr(settings.openai, "embedding_model_version", "") or "",
            redis_runtime=infra.redis,
            cache_ttl_seconds=getattr(settings.redis, "embedding_cache_ttl_seconds", 0) or 0,
        ),
        collection_name=infra.qdrant.local_life_parent_child_collection,
        vector_name=infra.qdrant.knowledge_vector_name,
        vector_size=infra.qdrant.knowledge_vector_size,
        distance=infra.qdrant.knowledge_distance,
    )


def _build_local_life_query_router() -> LocalLifeQueryRouter:
    return LocalLifeQueryRouter()


def _build_tool_deps(
    rag_orchestrator: RAGOrchestratorPort,
    *,
    java_business_client: Any | None = None,
) -> ToolDeps:
    planner = ToolPlanner()
    executor = ToolExecutor(
        java_business_client=java_business_client,
    )
    return ToolDeps(
        planner=planner,
        executor=executor,
        result_normalizer=ToolResultNormalizer(),
    )


def _build_streaming_deps(settings: Settings, infra: InfrastructureClients) -> StreamingDeps:
    llm_answerer = None
    if settings.prefer_real_adapters and infra.openai is not None:
        llm_answerer = OpenAIAnswerComposeAdapter(
            runtime=infra.openai,
            model=infra.openai.default_model,
            temperature=0.0,
        )
    return StreamingDeps(
        answer_composer=AnswerComposer(llm_answerer=llm_answerer),
        finalizer=Finalizer(settings=settings),
    )


def _build_workflow_checkpointer(settings: Settings) -> object | None:
    if not settings.workflow_checkpoint_enabled:
        return None
    if SqliteSaver is None:
        return None

    sqlite_path = Path(settings.workflow_checkpoint_sqlite_path).expanduser()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(sqlite_path), check_same_thread=False)
    return SqliteSaver(connection)


def _build_model_gateway(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[ModelGatewayPort, AdapterStatus]:
    fallback = HeuristicModelGateway()
    if settings.prefer_real_adapters and infra.openai is not None:
        return (
            OpenAIBackedModelGateway(runtime=infra.openai, fallback=fallback, intent_gate=HeuristicIntentGate()),
            AdapterStatus(
                name="model_gateway",
                mode="real",
                ready=True,
                details={
                    "backend": "openai_responses",
                    "fallback": "heuristic",
                    "model": infra.openai.default_model,
                },
            ),
        )
    return (
        fallback,
        AdapterStatus(
            name="model_gateway",
            mode="fallback",
            ready=True,
            details={"backend": "heuristic", "reason": "openai_unavailable_or_disabled"},
        ),
    )


def _build_rag_runtime_details(
    settings: Settings,
    infra: InfrastructureClients,
    *,
    chunks: tuple[KnowledgeChunk, ...],
    load_error: Optional[Exception],
    fallback_reason: str,
) -> dict[str, Any]:
    qdrant_available = infra.qdrant is not None
    openai_available = infra.openai is not None
    qdrant_client = getattr(infra.qdrant, "client", None) if infra.qdrant is not None else None
    openai_client = getattr(infra.openai, "client", None) if infra.openai is not None else None
    dense_query_capable = bool(
        qdrant_client is not None
        and (callable(getattr(qdrant_client, "query_points", None)) or callable(getattr(qdrant_client, "search", None)))
    )
    metadata_query_capable = bool(qdrant_client is not None and callable(getattr(qdrant_client, "query_points", None)))
    embedding_capable = bool(
        openai_client is not None
        and callable(getattr(getattr(openai_client, "embeddings", None), "create", None))
    )
    online_dense_enabled = bool(settings.enable_online_dense_retrieval)
    online_metadata_enabled = bool(settings.enable_online_dense_retrieval or settings.enable_online_sparse_retrieval)
    online_dense_available = bool(
        online_dense_enabled
        and qdrant_available
        and openai_available
        and load_error is None
        and dense_query_capable
        and embedding_capable
    )
    online_metadata_available = bool(
        online_metadata_enabled
        and qdrant_available
        and openai_available
        and load_error is None
        and metadata_query_capable
        and embedding_capable
    )
    snapshot_loaded = bool(chunks)
    details: dict[str, Any] = {
        "backend": "qdrant_snapshot" if snapshot_loaded else "in_memory_chunks",
        "runtime_mode": "snapshot" if snapshot_loaded else "fallback",
        "snapshot_loaded": snapshot_loaded,
        "snapshot_chunk_count": len(chunks),
        "snapshot_source": "qdrant" if snapshot_loaded else "bundled_defaults",
        "qdrant_available": qdrant_available,
        "openai_available": openai_available,
        "dense_query_capable": dense_query_capable,
        "metadata_query_capable": metadata_query_capable,
        "embedding_capable": embedding_capable,
        "online_dense_enabled": online_dense_enabled,
        "online_dense_available": online_dense_available,
        "online_metadata_enabled": online_metadata_enabled,
        "online_metadata_available": online_metadata_available,
        "reason": fallback_reason or ("qdrant_snapshot_loaded" if snapshot_loaded else "qdrant_unavailable_empty_or_disabled"),
        "fallback_reason": fallback_reason,
        "knowledge_collection": infra.qdrant.local_life_hybrid_collection if infra.qdrant is not None else None,
    }
    if load_error is not None:
        details["fallback_from"] = "qdrant"
        details["error"] = type(load_error).__name__
    elif not snapshot_loaded:
        details["fallback_from"] = "qdrant" if qdrant_available else "none"
    return details


def _build_rag_orchestrator(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[HybridRAGOrchestrator, AdapterStatus]:
    load_error: Optional[Exception] = None
    chunks: tuple[KnowledgeChunk, ...] = ()
    if settings.prefer_real_adapters and infra.qdrant is not None:
        try:
            chunks = _load_qdrant_knowledge_chunks(infra.qdrant)
        except Exception as exc:  # pragma: no cover - defensive fallback
            load_error = exc
        if load_error is not None and not settings.allow_in_memory_fallback:
            raise RuntimeError("Qdrant knowledge runtime is unavailable and in-memory fallback is disabled") from load_error
        if not chunks and not settings.allow_in_memory_fallback:
            raise RuntimeError("Qdrant knowledge runtime is unavailable and in-memory fallback is disabled")

    active_chunks = chunks or DEFAULT_KNOWLEDGE_CHUNKS
    parent_child_resolver = ParentChildResolver(active_chunks)
    filter_builder = QdrantFilterBuilder()
    rewrite_service = _build_query_rewrite_service(settings, infra)
    dense_retriever = _build_dense_retriever(settings, infra, active_chunks, parent_child_resolver, filter_builder)
    sparse_retriever = _build_sparse_retriever(settings, infra, active_chunks, parent_child_resolver, filter_builder)
    metadata_retriever = _build_metadata_retriever(settings, infra, active_chunks, parent_child_resolver, filter_builder)
    reranker = _build_reranker(settings)

    orchestrator = HybridRAGOrchestrator(
        settings=settings,
        knowledge_chunks=active_chunks,
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
        metadata_retriever=metadata_retriever,
        reranker=reranker,
        rewrite_service=rewrite_service,
        parent_child_resolver=parent_child_resolver,
    )

    if chunks:
        return (
            orchestrator,
            AdapterStatus(
                name="rag_runtime",
                mode="real",
                ready=True,
                details={
                    **_build_rag_runtime_details(
                        settings,
                        infra,
                        chunks=chunks,
                        load_error=load_error,
                        fallback_reason="",
                    ),
                    "chunk_count": len(chunks),
                    "llm_rewrite_enabled": settings.enable_llm_query_rewrite,
                },
            ),
        )

    return (
        orchestrator,
        AdapterStatus(
            name="rag_runtime",
            mode="fallback",
            ready=True,
            details={
                **_build_rag_runtime_details(
                    settings,
                    infra,
                    chunks=chunks,
                    load_error=load_error,
                    fallback_reason="qdrant_unavailable_empty_or_disabled",
                ),
                "llm_rewrite_enabled": settings.enable_llm_query_rewrite,
            },
        ),
    )


def _build_sparse_query_adapter():
    class TokenBagSparseQueryAdapter:
        def encode(self, text: str) -> Mapping[str, Any]:
            tokens = tuple(_tokenize_sparse_query(text))
            return {
                "indices": [
                    _stable_sparse_index(token) for token in tokens
                ],
                "values": [1.0 for _ in tokens],
            }

    return TokenBagSparseQueryAdapter()


def _tokenize_sparse_query(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(token.lower() for token in _SPARSE_TOKEN_PATTERN.findall(text))


def _stable_sparse_index(token: str) -> int:
    digest = hashlib.sha1(token.lower().encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % 2_000_000_000


def _build_repository_bundle(infra: InfrastructureClients) -> RepositoryBundle:
    if infra.postgres is None:
        return RepositoryBundle()

    session_factory = infra.postgres.session_factory
    return RepositoryBundle(
        outbox=OutboxRepository(session_factory),
        memory_outbox=MemoryOutboxRepository(session_factory),
        preferences=UserPreferenceRepository(session_factory),
        profile_projection=UserProfileProjectionRepository(session_factory),
        memory_traces=MemoryTraceRepository(session_factory),
    )


def _load_qdrant_knowledge_chunks(runtime: QdrantRuntime) -> tuple[KnowledgeChunk, ...]:
    client = runtime.client
    scroll = getattr(client, "scroll", None)
    if not callable(scroll):
        return ()

    loaded: list[KnowledgeChunk] = []
    next_offset: Any = None
    while True:
        page = scroll(
            collection_name=runtime.local_life_hybrid_collection,
            limit=128,
            with_payload=True,
            with_vectors=False,
            offset=next_offset,
        )
        points, next_offset = _normalize_scroll_page(page)
        for point in points:
            chunk = _point_to_knowledge_chunk(point)
            if chunk is not None:
                loaded.append(chunk)
        if not next_offset:
            break
    return tuple(loaded)


def _normalize_scroll_page(page: Any) -> tuple[Sequence[Any], Any]:
    if isinstance(page, tuple) and len(page) == 2:
        return page[0] or (), page[1]
    points = getattr(page, "points", None)
    next_offset = getattr(page, "next_page_offset", None)
    if points is not None:
        return points or (), next_offset
    if isinstance(page, Mapping):
        return page.get("points", ()) or (), page.get("next_page_offset")
    return (), None


def _point_to_knowledge_chunk(point: Any) -> Optional[KnowledgeChunk]:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, Mapping):
        payload = point.get("payload")
    if not isinstance(payload, Mapping):
        return None
    chunk_id = payload.get("chunk_id") or getattr(point, "id", None) or (point.get("id") if isinstance(point, Mapping) else None)
    extended_payload = dict(payload)
    if chunk_id is not None:
        extended_payload.setdefault("chunk_id", chunk_id)
    return KnowledgeChunk.from_payload(
        extended_payload,
        fallback_chunk_id=str(chunk_id) if chunk_id is not None else None,
        fallback_document_id=str(
            payload.get("document_id") or payload.get("doc_id") or payload.get("source_id") or ""
        )
        or None,
    )


def _build_session_context_store(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[SessionContextPort, AdapterStatus]:
    if settings.prefer_real_adapters and infra.redis is not None:
        return (
            RedisSessionContextStore(infra.redis),
            AdapterStatus(
                name="session_context_store",
                mode="real",
                ready=True,
                details={"backend": "redis", "truth_boundary": "short_term_session", "supports_load_any": True},
            ),
        )
    if not _memory_fallback_allowed(settings):
        raise RuntimeError("Redis session context store is unavailable and in-memory fallback is disabled")
    return (
        InMemorySessionContextStore(),
        AdapterStatus(
            name="session_context_store",
            mode="fallback",
            ready=True,
            details={"backend": "in_memory", "reason": "redis_unavailable_or_disabled", "supports_load_any": True},
        ),
    )


def _build_async_log_store(settings: Settings, repositories: RepositoryBundle) -> tuple[object, AdapterStatus]:
    if settings.prefer_real_adapters and repositories.outbox is not None:
        return (
            OutboxAsyncLogStore(repositories.outbox),
            AdapterStatus(
                name="async_log_store",
                mode="real",
                ready=True,
                details={"backend": "postgres_outbox", "path": "outbox", "payload_shape": "typed_or_legacy_mapping"},
            ),
        )
    if not _memory_fallback_allowed(settings):
        raise RuntimeError("Outbox async log store is unavailable and in-memory fallback is disabled")
    return (
        InMemoryAsyncLogStore(),
        AdapterStatus(
            name="async_log_store",
            mode="fallback",
            ready=True,
            details={"backend": "in_memory", "reason": "postgres_outbox_unavailable_or_disabled"},
        ),
    )


def _build_preference_store(
    repositories: RepositoryBundle,
) -> tuple[Optional[DurablePreferenceStore], AdapterStatus]:
    repository = repositories.preferences
    if repository is not None:
        return (
            DurablePreferenceStore(repository),
            AdapterStatus(
                name="preference_store",
                mode="real",
                ready=True,
                details={"backend": "postgres", "wired": True},
            ),
        )
    return (
        None,
        AdapterStatus(
            name="preference_store",
            mode="unavailable",
            ready=False,
            details={"backend": "none", "wired": False},
        ),
    )


def _build_profile_projection_store(
    repositories: RepositoryBundle,
) -> tuple[Optional[DurableProfileProjectionStore], AdapterStatus]:
    repository = repositories.profile_projection
    if repository is not None:
        return (
            DurableProfileProjectionStore(repository),
            AdapterStatus(
                name="profile_projection_store",
                mode="real",
                ready=True,
                details={"backend": "postgres", "wired": True},
            ),
        )
    return (
        None,
        AdapterStatus(
            name="profile_projection_store",
            mode="unavailable",
            ready=False,
            details={"backend": "none", "wired": False},
        ),
    )


def _build_durable_memory_backend(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[object, object, AdapterStatus, AdapterStatus] | None:
    if not (settings.prefer_real_adapters and infra.postgres is not None and infra.qdrant is not None and infra.openai is not None):
        return None
    embedding_adapter = _build_memory_embedding_adapter(settings, infra)
    memory_vector_size = _resolve_memory_vector_size(settings, embedding_adapter)
    repository = LongTermMemoryRepository(infra.postgres.session_factory)
    index = QdrantLongTermMemoryIndex(
        client=infra.qdrant.client,
        collection_name=infra.qdrant.memory_collection,
        vector_size=memory_vector_size,
        vector_name=infra.qdrant.memory_vector_name,
        distance=settings.qdrant.memory_distance,
        embedding_adapter=embedding_adapter,
    )
    memory_outbox = MemoryOutboxRepository(infra.postgres.session_factory)
    long_term_store = DurableLongTermMemoryStore(
        repository=repository,
        index=index,
        memory_outbox_repository=memory_outbox,
    )
    semantic_store = DurableSemanticMemoryStore(long_term_store=long_term_store)
    long_term_status = AdapterStatus(
        name="long_term_memory_store",
        mode="real",
        ready=True,
        details={
            "backend": "postgres+qdrant",
            "truth_boundary": "durable_memory",
        },
    )
    semantic_status = AdapterStatus(
        name="semantic_memory_store",
        mode="real",
        ready=True,
        details={
            "backend": "postgres+qdrant",
            "requested_backend": "postgres+qdrant",
            "reason": "durable_semantic_memory_backend_integrated",
        },
    )
    return long_term_store, semantic_store, long_term_status, semantic_status


def _build_semantic_memory_store(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[object, AdapterStatus]:
    if settings.prefer_real_adapters and infra.qdrant is not None:
        requested_backend = "qdrant"
    else:
        requested_backend = "none"
    if not _memory_fallback_allowed(settings):
        raise RuntimeError("Semantic memory store is unavailable and fallback is disabled")
    return (
        NoOpSemanticMemoryStore(),
        AdapterStatus(
            name="semantic_memory_store",
            mode="noop",
            ready=True,
            details={
                "backend": "noop",
                "requested_backend": requested_backend,
                "reason": "fallback_allowed_or_explicit_dev_noop",
            },
        ),
    )


def _build_long_term_memory_store(
    settings: Settings,
    infra: InfrastructureClients,
) -> tuple[object, AdapterStatus]:
    if not _memory_fallback_allowed(settings):
        raise RuntimeError("Long-term memory store is unavailable and in-memory fallback is disabled")
    return (
        InMemoryLongTermMemoryStore(),
        AdapterStatus(
            name="long_term_memory_store",
            mode="fallback",
            ready=True,
            details={"backend": "in_memory", "reason": "postgres_qdrant_unavailable_or_disabled"},
        ),
    )


def _build_runtime_profile(settings: Settings, runtime_status: RuntimeDependencyStatus) -> RuntimeProfile:
    core_component_names = {
        "model_gateway",
        "rag_orchestrator",
        "rag_route_gate",
        "session_context_store",
        "async_log_store",
        "java_business_client",
        "preference_store",
        "long_term_store",
        "semantic_memory_store",
        "postgres",
        "redis",
        "qdrant",
        "openai",
    }
    component_modes = tuple(
        RuntimeComponentMode(
            name=adapter.name,
            mode=adapter.mode,
            ready=adapter.ready,
            details=dict(adapter.details),
        )
        for adapter in runtime_status.adapters
        if adapter.name in core_component_names
    )
    if not settings.prefer_real_adapters:
        profile_name = "dev_fallback"
    elif component_modes and all(component.mode == "real" and component.ready for component in component_modes):
        profile_name = "full"
    else:
        profile_name = "partial"
    return RuntimeProfile(
        name=profile_name,
        components=component_modes,
        bootstrap_errors=runtime_status.bootstrap_errors,
    )


def _adapter_status(name: str, available: bool, mode: str) -> AdapterStatus:
    resolved_mode = mode if available else "unavailable"
    return AdapterStatus(
        name=name,
        mode=resolved_mode,
        ready=available,
        details={},
    )


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    def walk(value: Any) -> Optional[str]:
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, Mapping):
            for key in ("output_text", "text", "content"):
                candidate = value.get(key)
                result = walk(candidate)
                if result:
                    return result
            for child in value.values():
                result = walk(child)
                if result:
                    return result
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for child in value:
                result = walk(child)
                if result:
                    return result
        return None

    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        text = walk(dumped)
        if text:
            return text
    text = walk(response)
    if text:
        return text
    raise RuntimeError("No textual classification output returned by OpenAI runtime")


def _safe_intent(value: Any) -> IntentType:
    try:
        return IntentType(str(value))
    except Exception:
        return IntentType.EXPLAIN


def _safe_style(value: Any, fallback: Optional[OutputStyle]) -> Optional[OutputStyle]:
    if value is None:
        return fallback
    try:
        return OutputStyle(str(value))
    except Exception:
        return fallback


def _safe_required_action(value: Any, intent: IntentType) -> str:
    try:
        return str(value)
    except Exception:
        if intent in {IntentType.RECOMMEND}:
            return "tool_call"
        if intent in {
            IntentType.EXPLAIN,
            IntentType.COMPARE,
            IntentType.SUMMARY,
            IntentType.FOLLOW_UP,
        }:
            return "rag_retrieval"
        return "direct_answer"


def _normalize_local_life_intent(value: Any) -> Optional[str]:
    text = _optional_str(value)
    if text is None:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "recommend": "recommend",
        "restaurant_recommendation": "recommend",
        "local_life_recommendation": "recommend",
        "search_restaurants": "recommend",
        "compare": "compare",
        "restaurant_comparison": "compare",
        "local_life_comparison": "compare",
        "detail": "detail",
        "restaurant_detail": "detail",
        "local_life_detail": "detail",
        "get_shop_detail": "detail",
        "coupon": "coupon",
        "restaurant_coupon": "coupon",
        "local_life_coupon": "coupon",
        "get_coupon_list": "coupon",
        "coupon_and_detail": "coupon_and_detail",
        "navigation": "navigation",
        "restaurant_navigation": "navigation",
        "distance_eta": "navigation",
        "restaurant_distance_eta": "navigation",
        "get_distance_eta": "navigation",
        "booking": "booking",
        "book": "booking",
        "restaurant_booking": "booking",
        "local_life_booking": "booking",
        "create_booking": "booking",
        "order_status": "order_status",
        "restaurant_order_status": "order_status",
        "local_life_order_status": "order_status",
        "get_order_status": "order_status",
        "create_order": "create_order",
        "order": "create_order",
        "cancel": "cancel_order",
        "cancel_order": "cancel_order",
        "refund": "refund_order",
        "refund_order": "refund_order",
    }
    return aliases.get(normalized)


def _local_life_generic_intent(action: str) -> IntentType:
    if action == "compare":
        return IntentType.COMPARE
    if action == "recommend":
        return IntentType.RECOMMEND
    return IntentType.FOLLOW_UP


def _enrich_local_life_slots(raw_intent: Optional[str], slots: Mapping[str, Any], command) -> Dict[str, Any]:
    enriched = dict(slots)
    local_life_intent = _normalize_local_life_intent(
        enriched.get("local_life_intent")
        or enriched.get("local_life_action")
        or enriched.get("tool_name")
        or enriched.get("intent")
        or raw_intent
    )
    if local_life_intent is None:
        local_life_intent = _infer_local_life_intent_from_command(command)
    if local_life_intent is None:
        return enriched
    enriched["domain"] = "local_life"
    enriched["local_life_intent"] = local_life_intent
    enriched.setdefault("question_type", local_life_intent)
    enriched.setdefault("query", command.message)
    if getattr(command, "topic_hint", None):
        enriched.setdefault("topic_hint", command.topic_hint)
        if _looks_like_local_life_context(command):
            enriched.setdefault("shop_name", command.topic_hint)
    client_context = getattr(command, "client_context", {}) or {}
    if isinstance(client_context, Mapping):
        if client_context.get("shopName") not in (None, ""):
            enriched.setdefault("shop_name", client_context.get("shopName"))
        if client_context.get("typeName") not in (None, ""):
            enriched.setdefault("category", client_context.get("typeName"))
        if client_context.get("shopId") not in (None, ""):
            enriched.setdefault("shop_id", client_context.get("shopId"))
        if client_context.get("location") not in (None, "", [], {}, ()):
            enriched.setdefault("location", client_context.get("location"))
        if client_context.get("city") not in (None, ""):
            enriched.setdefault("city", client_context.get("city"))
    scene, preferences = _infer_local_life_scene_preferences(command.message, enriched.get("preferences"))
    if scene and enriched.get("scene") in (None, ""):
        enriched["scene"] = scene
    if preferences:
        enriched["preferences"] = preferences
    return enriched


def _infer_local_life_intent_from_command(command) -> Optional[str]:
    message = str(getattr(command, "message", "") or "")
    compact = message.replace(" ", "")
    lowered = message.lower()
    client_context = getattr(command, "client_context", {}) or {}
    page = str(getattr(command, "page", "") or client_context.get("page") or client_context.get("entry") or "").lower()
    looks_local_life = page in {"meituan_search_box", "assistant", "ai", "shop", "shops", "detail"} or any(
        key in client_context for key in ("shopId", "shopName", "typeId", "typeName", "city", "location")
    )
    if not looks_local_life and not any(token in compact for token in ("吃饭", "火锅", "餐厅", "店", "优惠券", "团购", "订座", "预约", "订单")):
        return None
    has_coupon = any(token in lowered for token in ("coupon", "voucher", "discount")) or any(token in compact for token in ("优惠券", "团购", "券"))
    has_environment = any(
        token in lowered for token in ("environment", "review", "rating", "reputation", "scene", "quiet", "atmosphere", "worth")
    ) or any(token in compact for token in ("怎么样", "评价", "评分", "口碑", "环境", "安静", "氛围", "适合", "家庭聚餐", "带父母", "带长辈", "约会"))
    if has_coupon and has_environment:
        return "coupon_and_detail"
    if any(token in lowered for token in ("coupon", "voucher", "discount")) or any(token in compact for token in ("优惠券", "团购", "券")):
        return "coupon"
    if any(token in lowered for token in ("compare", "vs", "difference")) or any(token in compact for token in ("对比", "比较", "区别")):
        return "compare"
    if any(token in lowered for token in ("book", "reserve", "booking")) or any(token in compact for token in ("订座", "预约", "预订")):
        return "booking"
    if any(token in lowered for token in ("order status", "my order")) or "订单" in compact:
        return "order_status"
    if any(token in lowered for token in ("detail", "review", "rating", "worth")) or any(
        token in compact for token in ("详情", "评分", "口碑", "怎么样", "这家", "那家", "第一家", "第二家", "第三家")
    ):
        return "detail"
    return "recommend"


def _looks_like_local_life_context(command) -> bool:
    message = str(getattr(command, "message", "") or "")
    compact = message.replace(" ", "")
    client_context = getattr(command, "client_context", {}) or {}
    page = str(getattr(command, "page", "") or client_context.get("page") or client_context.get("entry") or "").lower()
    if page in {"meituan_search_box", "assistant", "ai", "shop", "shops", "detail"}:
        return True
    if any(key in client_context for key in ("shopId", "shopName", "typeId", "typeName", "city", "location")):
        return True
    return any(
        token in compact
        for token in ("吃饭", "火锅", "餐厅", "店", "优惠券", "团购", "订座", "预约", "订单", "对比", "哪家", "怎么样", "附近")
    )


def _infer_local_life_scene_preferences(message: Any, existing_preferences: Any) -> tuple[Optional[str], list[str]]:
    compact = str(message or "").replace(" ", "")
    preferences = []
    if isinstance(existing_preferences, list):
        preferences.extend(str(item) for item in existing_preferences if str(item or "").strip())
    scene = None
    if any(token in compact for token in ("爸妈", "父母", "长辈", "老人")):
        scene = "family_dinner"
        preferences.extend(["elder_friendly", "family_friendly"])
    if any(token in compact for token in ("别太吵", "安静", "清静")):
        preferences.append("quiet")
    if "停车" in compact:
        preferences.append("parking_available")
    return scene, list(dict.fromkeys(preferences))


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_embedding_query(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return compact


def _coerce_reference_resolution(value: Any) -> Optional[ReferenceResolutionResult]:
    if value is None:
        return None
    if isinstance(value, ReferenceResolutionResult):
        return value
    if isinstance(value, Mapping):
        try:
            return ReferenceResolutionResult.model_validate(dict(value))
        except Exception:
            return None
    return None


def _coerce_retrieval_plan(value: Any) -> Optional[RetrievalPlan]:
    if value is None:
        return None
    if isinstance(value, RetrievalPlan):
        return value
    if isinstance(value, Mapping):
        try:
            return RetrievalPlan.model_validate(dict(value))
        except Exception:
            return None
    return None


def _coerce_rag_gate_payload(value: Any) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        payload = dict(value)
        if payload:
            return payload
    return None


def _build_cached_rag_gate(
    required_action: str,
    intent: IntentType,
    confidence: float,
    payload: Mapping[str, Any],
    slots: Mapping[str, Any],
) -> dict[str, Any]:
    route_candidate = _optional_str(payload.get("route_candidate") or slots.get("route_candidate"))
    normalized_action = str(required_action or "").strip().lower()
    allowed = normalized_action in {"rag_retrieval", "rag_plus_tool"}
    response_kind = "fallback"
    if not allowed:
        response_kind = route_candidate or (
            "low_info"
            if normalized_action == "clarify" or intent in {IntentType.FOLLOW_UP} and confidence < 0.5
            else "empty"
            if confidence <= 0.1
            else "low_info"
        )
    reason = route_candidate or normalized_action
    final_vote = "allow" if allowed else "deny"
    cached_vote = {
        "allowed": allowed,
        "reason": reason,
        "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
        "response_kind": response_kind,
        "precheck_skip_memory": False,
        "final_vote": final_vote,
        "rule_vote": None,
        "llm_vote": None,
        "metadata": {
            "source": "understanding_bundle",
            "decision": normalized_action,
            "intent": intent.value,
        },
    }
    return cached_vote
