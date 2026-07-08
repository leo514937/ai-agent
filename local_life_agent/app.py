"""FastAPI HTTP wrapper for the local life agent runtime.

Provides endpoints for health check, streaming chat, feedback, approval,
and session state inspection as expected by the Java backend.
"""

from __future__ import annotations

try:
    import nest_asyncio
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    nest_asyncio = None
else:  # pragma: no branch
    nest_asyncio.apply()

import json
import queue
import threading
from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from local_life_agent.agent import run_agent_graph
from local_life_agent.domain.schemas import UserContext
from local_life_agent.location_utils import normalize_location_payload
from local_life_agent.observability.file_logger import get_python_service_logger
from local_life_agent.streaming.runtime import (
    TurnControl,
    TurnStatus,
    bind_stream_handler,
    bind_turn_control,
    get_turn_registry,
)
from local_life_agent.streaming.cancellation_policy import decide_cancellation_action
from local_life_agent.streaming.preview_policy import sanitize_preview_text
from local_life_agent.streaming.status_events import (
    make_preview_block,
    make_status_block,
    make_trace_block,
)
from local_life_agent.session.store import get_session_store

app = FastAPI(title="Local Life Agent Service", version="1.0.0")
_FILE_LOGGER = get_python_service_logger()


class ChatRequest(BaseModel):
    user_id: str = Field(default="guest")
    session_id: str = Field(min_length=1)
    trace_id: str = Field(default="")
    turn_id: str = Field(default="")
    page: str = Field(default="assistant")
    message: str = Field(min_length=1, max_length=4000)
    response_mode: str = Field(default="default")
    topic_hint: str = Field(default="")
    history_summary: str = Field(default="")
    client_context: dict[str, Any] = Field(default_factory=dict)


class ChatCancelRequest(BaseModel):
    session_id: str = Field(default="")
    turn_id: str = Field(default="")
    trace_id: str = Field(default="")
    reason: str = Field(default="user_stop")


def _location_payload_from_client_context(client_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(client_context or {})
    for key in ("user_location", "location", "geo", "position"):
        nested = normalize_location_payload(payload.get(key))
        if nested:
            merged = dict(payload)
            merged.update(nested)
            payload = merged
            break

    location_name = str(
        payload.get("location_name")
        or payload.get("name")
        or payload.get("label")
        or payload.get("text")
        or payload.get("poi")
        or payload.get("address")
        or payload.get("district")
        or payload.get("business_area")
        or payload.get("city")
        or ""
    ).strip()
    if location_name and not payload.get("location_name"):
        payload["location_name"] = location_name
    return normalize_location_payload(payload)


def _user_context_from_client_context(client_context: dict[str, Any] | None) -> tuple[UserContext | None, dict[str, Any]]:
    location = _location_payload_from_client_context(client_context)
    if not location:
        return None, {}

    lat = location.get("lat")
    lng = location.get("lng")
    has_coordinates = lat is not None and lng is not None
    if has_coordinates:
        status = str(location.get("location_status") or location.get("status") or "provided").strip() or "provided"
        missing_reason = ""
    else:
        status = str(location.get("location_status") or location.get("status") or "provided").strip() or "provided"
        missing_reason = ""

    user_context = UserContext(
        location_name=str(location.get("location_name") or location.get("name") or location.get("label") or ""),
        lat=float(lat) if has_coordinates else None,
        lng=float(lng) if has_coordinates else None,
        location_status=status,
        location_source=str(location.get("location_source") or "client_context"),
        requires_location=False,
        location_missing_reason=missing_reason,
    )
    return user_context, location


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "local-life-agent-service",
        "version": "1.0.0"
    }


@app.get("/live")
async def live():
    return {
        "status": "ok"
    }


@app.post("/internal/v1/chat/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(_stream_chat_events(request), media_type="text/event-stream")


def _event_block(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_chat_events(request: ChatRequest):
    registry = get_turn_registry()
    trace_id = request.trace_id or "trace-anon"
    session_id = request.session_id or "session-anon"
    turn_id = request.turn_id or "turn-anon"
    registry.start_turn(session_id, turn_id, trace_id)

    delta_queue: queue.Queue[str] = queue.Queue()
    finished = threading.Event()
    result_box: dict[str, Any] = {}

    def _runner() -> None:
        control = TurnControl(registry=registry, session_id=session_id, turn_id=turn_id, trace_id=trace_id)
        user_context, user_location = _user_context_from_client_context(request.client_context)
        try:
            with bind_turn_control(control), bind_stream_handler(delta_queue.put):
                kwargs: dict[str, Any] = {
                    "session_id": request.session_id,
                    "trace_id": request.trace_id,
                    "turn_id": request.turn_id,
                }
                if user_context is not None:
                    kwargs["user_context"] = user_context
                    kwargs["user_location"] = user_location
                result_box["response"] = run_agent_graph(request.message, **kwargs)
            registry.mark_finished(session_id, turn_id, getattr(result_box.get("response"), "answer_text", ""))
        except Exception as exc:  # pragma: no cover - safety net for stream lifecycle
            result_box["error"] = exc
            registry.mark_failed(session_id, turn_id, str(exc))
        finally:
            finished.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()

    _FILE_LOGGER.info(
        "chat_stream_request session_id=%s trace_id=%s turn_id=%s page=%s message=%s",
        request.session_id or "",
        request.trace_id or "",
        request.turn_id or "",
        request.page or "",
        request.message or "",
    )
    def event_stream():
        disconnected = False
        try:
            yield make_trace_block(
                trace_id,
                session_id,
                turn_id,
                "hm-dianping-python/v1",
                page=request.page,
                user_id=request.user_id,
            )
            yield _event_block(
                "input_normalized",
                {
                    "event_type": "input_normalized",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "payload": {"normalized_text": request.message, "input_type": "text"},
                },
            )

            while not finished.is_set() or not delta_queue.empty():
                try:
                    delta = delta_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                yield _event_block(
                    "answer_delta",
                    {
                        "event_type": "answer_delta",
                        "trace_id": trace_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {"delta_text": delta},
                    },
                )
                preview_text = sanitize_preview_text(delta, verified=False)
                if preview_text:
                    yield make_preview_block(
                        trace_id,
                        session_id,
                        turn_id,
                        preview_text,
                        verified=False,
                        source="answer_delta",
                    )

            response = result_box.get("response")
            error = result_box.get("error")
            if error is not None:
                yield _event_block(
                    "error",
                    {
                        "event_type": "error",
                        "trace_id": trace_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "payload": {
                            "code": "GRAPH_EXECUTION_ERROR",
                            "message": str(error),
                            "stage": "graph_execution",
                        },
                    },
                )
                yield make_status_block(
                    trace_id,
                    session_id,
                    turn_id,
                    "failed",
                    stage="graph_execution",
                    detail={"error": str(error)},
                )
                return
            answer_text = getattr(response, "answer_text", "") if response is not None else ""
            cards = getattr(response, "cards", []) if response is not None else []
            final_payload = {
                "answer_text": answer_text,
                "mode": "remote",
                "source": "learning-agent-service",
                "page": request.page,
                "current_topic": "local_life",
                "fallback": False,
                "suggested_replies": [],
                "shops": cards or [],
                "vouchers": [],
                "cards": cards or [],
                "next_steps": [],
                "task_chain": [],
            }
            _FILE_LOGGER.info(
                "chat_stream_final trace_id=%s session_id=%s answer=%s shops=%s",
                trace_id,
                session_id,
                answer_text,
                len(cards or []),
            )
            yield _event_block(
                "final",
                {
                    "event_type": "final",
                "trace_id": trace_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "payload": {**final_payload, "verified": True},
            },
            )
            yield make_status_block(
                trace_id,
                session_id,
                turn_id,
                "completed",
                stage="streaming",
                detail={"verified": True, "card_count": len(cards or [])},
            )
        finally:
            if not finished.is_set():
                disconnected = True
                registry.mark_client_disconnected(session_id, turn_id)
            if disconnected:
                _FILE_LOGGER.info("chat_stream_disconnected session_id=%s turn_id=%s", session_id, turn_id)

    return event_stream()


@app.post("/internal/v1/feedback/report")
async def report_feedback(request: Request):
    return {"status": "ok"}


@app.post("/internal/v1/approval/submit")
async def submit_approval(request: Request):
    return {"status": "ok"}


@app.post("/internal/v1/chat/cancel")
async def cancel_chat(request: ChatCancelRequest):
    registry = get_turn_registry()
    session_id = request.session_id or "session-anon"
    turn_id = request.turn_id or "turn-anon"
    trace_id = request.trace_id or "trace-anon"
    registry.start_turn(session_id, turn_id, trace_id)
    record = registry.mark_user_cancelled(session_id, turn_id, reason=request.reason or "user_stop")
    return {
        "status": "ok",
        "turn_status": record.status.value if record is not None else TurnStatus.USER_CANCELLED.value,
        "cancel_action": decide_cancellation_action("user_cancel"),
        "session_id": session_id,
        "turn_id": turn_id,
        "reason": request.reason or "user_stop",
    }


@app.get("/internal/v1/session/{session_id}/state")
async def get_session_state(session_id: str):
    store = get_session_store()
    state = store.load(session_id)
    return state.model_dump() if hasattr(state, "model_dump") else {}
