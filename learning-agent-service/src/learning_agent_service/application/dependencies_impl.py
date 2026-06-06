from __future__ import annotations



import logging

import json

import hashlib

import re






from pathlib import Path

from typing import Any, Mapping, Optional, Sequence



from learning_agent_service.config import Settings, get_settings

from learning_agent_service.domain import (

    ReferenceResolutionResult,

    RetrievalPlan,

)


from learning_agent_service.domain.enums import IntentType, OutputStyle

from learning_agent_service.domain.protocols import (

    ModelGatewayPort,

    RAGOrchestratorPort,

    RagRouteGatePort,

    SessionContextPort,

)

from learning_agent_service.infrastructure.db.factories import InfrastructureClients, build_infrastructure_clients


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

from learning_agent_service.rag.local_life import LocalLifeParentChildRetriever

from learning_agent_service.adapters.java_business import JavaBusinessClient

from learning_agent_service.local_life.assistant import LocalLifeModelAssistant

from learning_agent_service.local_life.query_router import LocalLifeQueryRouter

from learning_agent_service.application.rag_gate import RagRouteGate

from learning_agent_service.tools.orchestrator import (

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





from .container import (
    AppDependencies,
    ApplicationRuntime,
    MemoryDeps,
    OpenAIAnswerComposeAdapter,
    OpenAIBackedModelGateway,
    OpenAIHyDEAdapter,
    OpenAIQueryRewriteAdapter,
    OpenAIRagGateJudge,
    RagDeps,
    RagGateDeps,
    RepositoryBundle,
    StreamingDeps,
    ToolDeps,
    UnderstandingDeps,
    _build_memory_embedding_adapter,
    _build_openai_embedding_adapter,
    _resolve_memory_vector_size,
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

    runtime.local_life_retriever = local_life_retriever

    runtime.local_life_query_router = local_life_query_router

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

    ctx = SqliteSaver.from_conn_string(str(sqlite_path))
    saver = ctx.__enter__()
    saver._conn_ctx = ctx
    return saver





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

    warmup_pending: bool = False,

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
    runtime_mode = "snapshot" if snapshot_loaded else "warming" if warmup_pending else "fallback"
    if fallback_reason:
        reason = fallback_reason
    elif snapshot_loaded:
        reason = "qdrant_snapshot_loaded"
    elif warmup_pending:
        reason = "qdrant_warmup_pending_async"
    else:
        reason = "qdrant_unavailable_empty_or_disabled"

    details: dict[str, Any] = {

        "backend": "qdrant_snapshot" if snapshot_loaded else "in_memory_chunks",

        "runtime_mode": runtime_mode,

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

        "reason": reason,

        "fallback_reason": fallback_reason,

        "knowledge_collection": infra.qdrant.local_life_hybrid_collection if infra.qdrant is not None else None,

    }

    if warmup_pending:
        details["warmup_pending"] = True
        details["warmup_strategy"] = "async"

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


    warmup_pending = bool(
        settings.prefer_real_adapters
        and settings.allow_in_memory_fallback
        and infra.qdrant is not None
        and infra.openai is not None
        and not chunks
    )


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
                        warmup_pending=False,

                    ),

                    "chunk_count": len(chunks),

                    "llm_rewrite_enabled": settings.enable_llm_query_rewrite,

                },

            ),

        )



    if warmup_pending:
        return (

            orchestrator,

            AdapterStatus(

                name="rag_runtime",

                mode="warming",

                ready=True,

                details={

                    **_build_rag_runtime_details(

                        settings,

                        infra,

                        chunks=chunks,

                        load_error=load_error,

                        fallback_reason="qdrant_warmup_pending_async",

                        warmup_pending=True,

                    ),

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
                    warmup_pending=False,

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





def _parse_json_response(response: Any) -> Any:

    text = _extract_response_text(response)

    cleaned = text.strip()

    if cleaned.startswith("```"):

        lines = cleaned.splitlines()

        if lines[0].startswith("```"):

            lines = lines[1:]

        if lines and lines[-1].startswith("```"):

            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    try:

        return json.loads(cleaned)

    except json.JSONDecodeError as exc:

        import structlog

        logger = structlog.get_logger()

        logger.error("llm_json_parse_failed", text=text, cleaned=cleaned, error=str(exc))

        raise





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





def _enrich_local_life_slots(raw_intent: Optional[str], slots: Mapping[str, Any], command) -> dict[str, Any]:

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

__all__ = [name for name in globals() if not name.startswith("__")]
