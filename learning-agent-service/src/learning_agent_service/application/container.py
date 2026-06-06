from __future__ import annotations



import logging

import json

import hashlib

import re


import time

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from datetime import datetime, timezone

from dataclasses import dataclass


from typing import Any, Mapping, Optional



from learning_agent_service.config import Settings

from learning_agent_service.domain import (

    ChatTurnCommand,

    FastDecision,

    TurnUnderstandingRequest,

)

from learning_agent_service.domain.contracts import AnswerComposeRequest, SseEnvelope

from learning_agent_service.domain.enums import IntentType

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

from learning_agent_service.infrastructure.db.factories import InfrastructureClients

from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime


from learning_agent_service.infrastructure.repositories import (

    AdapterStatus,

    MemoryOutboxRepository,

    OutboxRepository,

    RuntimeDependencyStatus,

    RuntimeProfile,

    UserPreferenceRepository,

    UserProfileProjectionRepository,

)

from learning_agent_service.infrastructure.repositories.memory_trace_repository import MemoryTraceRepository




from learning_agent_service.memory.orchestrator import MemoryOrchestrator





from learning_agent_service.rag.heuristics import HeuristicIntentGate








from learning_agent_service.application.rag_gate import RagGateRequest, RagGateVote




try:

    from langgraph.checkpoint.sqlite import SqliteSaver

except Exception:  # pragma: no cover - optional dependency path

    SqliteSaver = None



_SPARSE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")

_LOGGER = logging.getLogger(__name__)


def _normalize_embedding_query(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())





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

        return _parse_json_response(response)





def _parse_json_response(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if text is None:
        output = getattr(response, "output", None)
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, Mapping):
                            piece = part.get("text") or part.get("output_text") or part.get("value")
                        else:
                            piece = getattr(part, "text", None) or getattr(part, "output_text", None) or getattr(part, "value", None)
                        if piece:
                            chunks.append(str(piece))
                elif content:
                    chunks.append(str(content))
            text = "".join(chunks)
        elif output is not None:
            text = str(output)
        else:
            text = ""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        payload = json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(cleaned[start : end + 1])
            except Exception:
                return {}
        else:
            return {}
    return payload if isinstance(payload, dict) else {}


def _safe_intent(value: Any) -> IntentType | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    try:
        return IntentType(lowered)
    except Exception:
        try:
            return IntentType[text.upper()]
        except Exception:
            return None


def _enrich_local_life_slots(intent: str | None, key_slots: dict[str, Any], command: ChatTurnCommand) -> dict[str, Any]:
    enriched = dict(key_slots)
    if intent:
        enriched.setdefault("intent", intent)
    if command.topic_hint and "topic_hint" not in enriched:
        enriched["topic_hint"] = command.topic_hint
    return enriched


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

        return _parse_json_response(response)





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

        payload = _parse_json_response(response)

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

        payload = _parse_json_response(response)

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






__all__ = [name for name in globals() if not name.startswith('__')]
