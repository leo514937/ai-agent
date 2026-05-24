"""Main application entrypoint for the local life agent service."""

from __future__ import annotations

from dataclasses import dataclass, field
from json import dumps
from threading import Lock
from time import perf_counter
from typing import Any, Awaitable, Callable, Iterable, Optional

from learning_agent_service import __version__
from learning_agent_service.api.contracts import ChatStreamRequest, SseEnvelope
from learning_agent_service.api.compat import FastAPI as CompatFastAPI
from learning_agent_service.api.dependencies import LearningAgentService
from learning_agent_service.config import get_settings

FASTAPI_IMPORT_ERROR: Optional[Exception] = None

try:
    from fastapi import FastAPI
    from fastapi.responses import ORJSONResponse
except Exception as exc:  # pragma: no cover - fallback is intentional
    FASTAPI_IMPORT_ERROR = exc
    FastAPI = None  # type: ignore[assignment]
    ORJSONResponse = None  # type: ignore[assignment]

from learning_agent_service.api.router import create_api_router

AsgiApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]
CORE_REAL_DEPENDENCIES = {
    "model_gateway",
    "rag_runtime",
    "session_context_store",
    "async_log_store",
    "java_business_client",
    "redis",
    "postgres",
    "qdrant",
    "openai",
}


def _coerce_payload_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _compute_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[position], 3)


@dataclass
class ServiceMetricsRegistry:
    stream_requests_total: int = 0
    stream_failures_total: int = 0
    final_answers_total: int = 0
    final_answers_with_citations_total: int = 0
    final_answers_without_citations_total: int = 0
    clarification_cards_total: int = 0
    terminal_errors_total: int = 0
    grounded_answers_total: int = 0
    weakly_grounded_answers_total: int = 0
    ungrounded_answers_total: int = 0
    retrieval_empty_results_total: int = 0
    tool_results_skipped_total: int = 0
    tool_results_degraded_total: int = 0
    memory_retrieval_events_total: int = 0
    memory_promotion_events_total: int = 0
    first_event_latencies_ms: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def observe_stream(
        self,
        request: ChatStreamRequest,
        events: Iterable[SseEnvelope],
    ) -> Iterable[SseEnvelope]:
        started_at = perf_counter()
        first_event_observed = False

        def instrumented() -> Iterable[SseEnvelope]:
            nonlocal first_event_observed
            try:
                for event in events:
                    if not first_event_observed:
                        first_event_observed = True
                        self._record_first_event_latency((perf_counter() - started_at) * 1000)
                    self._observe_event(event)
                    yield event
            except Exception:
                self._increment_counter("stream_failures_total")
                raise
            finally:
                self._increment_counter("stream_requests_total")

        return instrumented()

    def _record_first_event_latency(self, latency_ms: float) -> None:
        with self._lock:
            self.first_event_latencies_ms.append(round(latency_ms, 3))
            if len(self.first_event_latencies_ms) > 512:
                self.first_event_latencies_ms.pop(0)

    def _increment_counter(self, field_name: str) -> None:
        with self._lock:
            setattr(self, field_name, getattr(self, field_name) + 1)

    def _observe_event(self, event: SseEnvelope) -> None:
        payload = _coerce_payload_mapping(getattr(event, "payload", {}))
        event_type = str(getattr(event, "event_type", "") or "")
        with self._lock:
            if event_type == "final":
                self.final_answers_total += 1
                citations = payload.get("citations")
                citation_count = len(citations) if isinstance(citations, list) else 0
                if citation_count > 0:
                    self.final_answers_with_citations_total += 1
                else:
                    self.final_answers_without_citations_total += 1

                grounding_status = str(payload.get("grounding_status") or "not_grounded")
                if grounding_status == "grounded":
                    self.grounded_answers_total += 1
                elif grounding_status == "weakly_grounded":
                    self.weakly_grounded_answers_total += 1
                else:
                    self.ungrounded_answers_total += 1
            elif event_type == "clarification_card":
                self.clarification_cards_total += 1
            elif event_type == "error":
                self.terminal_errors_total += 1
            elif event_type == "memory_retrieval_result":
                self.memory_retrieval_events_total += 1
            elif event_type == "memory_promotion_result":
                self.memory_promotion_events_total += 1
            elif event_type == "retrieval_result":
                if int(payload.get("evidence_used_count") or 0) == 0:
                    self.retrieval_empty_results_total += 1
            elif event_type == "tool_result":
                if str(payload.get("status") or "") == "skipped":
                    self.tool_results_skipped_total += 1
                if bool(payload.get("degraded")) or str(payload.get("status") or "") == "degraded":
                    self.tool_results_degraded_total += 1

    def snapshot(self, readiness: dict[str, Any], infrastructure_status: dict[str, Any]) -> dict[str, Any]:
        dependency_status = _coerce_payload_mapping(infrastructure_status.get("dependency_status"))
        adapters = dependency_status.get("adapters")
        adapter_list = list(adapters) if isinstance(adapters, list) else []
        with self._lock:
            first_event_latencies_ms = list(self.first_event_latencies_ms)
            counters = {
                "stream_requests_total": self.stream_requests_total,
                "stream_failures_total": self.stream_failures_total,
                "final_answers_total": self.final_answers_total,
                "final_answers_with_citations_total": self.final_answers_with_citations_total,
                "final_answers_without_citations_total": self.final_answers_without_citations_total,
                "clarification_cards_total": self.clarification_cards_total,
                "terminal_errors_total": self.terminal_errors_total,
                "grounded_answers_total": self.grounded_answers_total,
                "weakly_grounded_answers_total": self.weakly_grounded_answers_total,
                "ungrounded_answers_total": self.ungrounded_answers_total,
                "retrieval_empty_results_total": self.retrieval_empty_results_total,
                "tool_results_skipped_total": self.tool_results_skipped_total,
                "tool_results_degraded_total": self.tool_results_degraded_total,
                "memory_retrieval_events_total": self.memory_retrieval_events_total,
                "memory_promotion_events_total": self.memory_promotion_events_total,
            }
        return {
            "service": "local-life-agent-service",
            "version": __version__,
            "readiness": readiness,
            "counters": counters,
            "latency_ms": {
                "first_event_avg": round(
                    sum(first_event_latencies_ms) / len(first_event_latencies_ms),
                    3,
                )
                if first_event_latencies_ms
                else 0.0,
                "first_event_p95": _compute_percentile(first_event_latencies_ms, 0.95),
            },
            "dependency_gauges": [
                {
                    "name": str(adapter.get("name") or ""),
                    "mode": str(adapter.get("mode") or ""),
                    "ready": bool(adapter.get("ready")),
                    "value": 1 if bool(adapter.get("ready")) else 0,
                    "details": dict(adapter.get("details") or {}),
                }
                for adapter in adapter_list
                if isinstance(adapter, dict)
            ],
        }


class InstrumentedLearningAgentService:
    def __init__(self, delegate: LearningAgentService, metrics_registry: ServiceMetricsRegistry) -> None:
        self._delegate = delegate
        self._metrics_registry = metrics_registry

    def run_stream(self, request: ChatStreamRequest) -> Iterable[SseEnvelope]:
        return self._metrics_registry.observe_stream(request, self._delegate.run_stream(request))


    def get_session_state(self, session_id: str):
        return self._delegate.get_session_state(session_id)

    def report_feedback(self, request):
        return self._delegate.report_feedback(request)

    def list_feedback_samples(self, limit: int = 50):
        return self._delegate.list_feedback_samples(limit=limit)

    def list_memory_records(self, user_id: str, scope: str | None = None, query: str | None = None, limit: int = 50):
        return self._delegate.list_memory_records(user_id=user_id, scope=scope, query=query, limit=limit)

    def list_memory_candidates(self, user_id: str, limit: int = 50):
        return self._delegate.list_memory_candidates(user_id=user_id, limit=limit)

    def get_memory_record(self, memory_id: str):
        return self._delegate.get_memory_record(memory_id)

    def list_memory_traces(
        self,
        user_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        limit: int = 20,
    ):
        return self._delegate.list_memory_traces(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            limit=limit,
        )

    def get_memory_trace(self, trace_id: str):
        return self._delegate.get_memory_trace(trace_id)

    def list_memory_access_logs(self, memory_id: str):
        return self._delegate.list_memory_access_logs(memory_id)

    def list_memory_deletion_jobs(self, limit: int = 50):
        return self._delegate.list_memory_deletion_jobs(limit=limit)

    def confirm_memory_candidate(self, candidate_id: str, request):
        return self._delegate.confirm_memory_candidate(candidate_id, request)

    def reject_memory_candidate(self, candidate_id: str, request):
        return self._delegate.reject_memory_candidate(candidate_id, request)

    def supersede_memory_record(self, memory_id: str, request):
        return self._delegate.supersede_memory_record(memory_id, request)

    def delete_memory_record(self, memory_id: str, request):
        return self._delegate.delete_memory_record(memory_id, request)


def _evaluate_readiness(app: Any) -> dict[str, Any]:
    infrastructure_status = _coerce_payload_mapping(getattr(app.state, "infrastructure_status", {}))
    runtime_profile = _coerce_payload_mapping(infrastructure_status.get("runtime_profile"))
    dependency_status = _coerce_payload_mapping(infrastructure_status.get("dependency_status"))
    adapters = dependency_status.get("adapters")
    adapter_list = list(adapters) if isinstance(adapters, list) else []
    bootstrap_errors = list(getattr(app.state, "bootstrap_errors", []) or [])
    settings = getattr(app.state, "settings", None)
    prefer_real_adapters = bool(getattr(settings, "prefer_real_adapters", True))
    blocking_dependencies: list[str] = []
    degraded_dependencies: list[str] = []

    for adapter in adapter_list:
        if not isinstance(adapter, dict):
            continue
        name = str(adapter.get("name") or "")
        mode = str(adapter.get("mode") or "")
        ready = bool(adapter.get("ready"))
        if not ready:
            degraded_dependencies.append(name)
        elif mode != "real":
            degraded_dependencies.append(name)
        if prefer_real_adapters and name in CORE_REAL_DEPENDENCIES and (not ready or mode != "real"):
            blocking_dependencies.append(name)

    if not adapter_list:
        ready = not bootstrap_errors
    else:
        ready = not bootstrap_errors and not blocking_dependencies

    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "bootstrap_ready": not bootstrap_errors,
        "prefer_real_adapters": prefer_real_adapters,
        "blocking_dependencies": blocking_dependencies,
        "degraded_dependencies": degraded_dependencies,
        "runtime_profile": runtime_profile,
        "bootstrap_errors": bootstrap_errors,
    }


def _build_fastapi_app(service: Optional[LearningAgentService] = None, app_cls: Any = None) -> Any:
    app_factory = app_cls or FastAPI or CompatFastAPI
    kwargs = {
        "title": "Local Life Agent Service",
        "version": __version__,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
    }
    if ORJSONResponse is not None:
        kwargs["default_response_class"] = ORJSONResponse
    app = app_factory(**kwargs)
    if service is None:
        from learning_agent_service.application.bootstrap import bootstrap_application

        bootstrap = bootstrap_application(app)
        service = bootstrap.learning_service
    else:
        app.state.settings = get_settings()
        app.state.bootstrap_errors = []
        app.state.infrastructure_status = {}
    app.state.service_metrics = ServiceMetricsRegistry()
    observed_service = InstrumentedLearningAgentService(service, app.state.service_metrics)
    app.state.learning_service = observed_service
    app.include_router(create_api_router(observed_service))

    @app.get("/health")
    async def health() -> dict[str, Any]:
        bootstrap_errors = list(getattr(app.state, "bootstrap_errors", []))
        return {
            "status": "ok",
            "service": "local-life-agent-service",
            "version": __version__,
            "bootstrap_ready": not bootstrap_errors,
            "bootstrap_errors": bootstrap_errors,
            "infrastructure": getattr(app.state, "infrastructure_status", {}),
        }

    @app.get("/meta")
    async def meta() -> dict[str, Any]:
        return {
            "service": "local-life-agent-service",
            "version": __version__,
            "settings": app.state.settings.safe_dump(),
            "infrastructure": getattr(app.state, "infrastructure_status", {}),
        }

    @app.get("/live")
    async def live() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "local-life-agent-service",
            "version": __version__,
        }

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        readiness = _evaluate_readiness(app)
        return {
            "status": readiness["status"],
            "ready": readiness["ready"],
            "service": "local-life-agent-service",
            "version": __version__,
            "bootstrap_ready": readiness["bootstrap_ready"],
            "prefer_real_adapters": readiness["prefer_real_adapters"],
            "blocking_dependencies": readiness["blocking_dependencies"],
            "degraded_dependencies": readiness["degraded_dependencies"],
            "runtime_profile": readiness["runtime_profile"],
            "bootstrap_errors": readiness["bootstrap_errors"],
        }

    @app.get("/dependency-status")
    async def dependency_status() -> dict[str, Any]:
        infrastructure = _coerce_payload_mapping(getattr(app.state, "infrastructure_status", {}))
        readiness = _evaluate_readiness(app)
        return {
            "service": "local-life-agent-service",
            "version": __version__,
            "ready": readiness["ready"],
            "runtime_profile": infrastructure.get("runtime_profile", {}),
            "dependency_status": infrastructure.get("dependency_status", {}),
        }

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        readiness = _evaluate_readiness(app)
        infrastructure = _coerce_payload_mapping(getattr(app.state, "infrastructure_status", {}))
        return app.state.service_metrics.snapshot(readiness, infrastructure)

    return app


def _build_fallback_asgi() -> AsgiApp:
    message = {
        "code": "DEPENDENCY_MISSING",
        "message": "FastAPI is not installed; install project dependencies to run the service.",
        "details": str(FASTAPI_IMPORT_ERROR) if FASTAPI_IMPORT_ERROR else None,
        "service": "local-life-agent-service",
        "version": __version__,
    }
    payload = dumps(message).encode("utf-8")

    async def fallback_app(
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope["type"] != "http":
            raise RuntimeError("Fallback ASGI app only supports HTTP.")

        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return fallback_app


def create_app(service: Optional[LearningAgentService] = None) -> Any:
    if FastAPI is None and service is None:
        return _build_fallback_asgi()
    return _build_fastapi_app(service=service, app_cls=FastAPI or CompatFastAPI)


app = create_app()
