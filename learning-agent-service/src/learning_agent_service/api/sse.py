from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from typing import Iterable, Iterator

from .compat import StreamingResponse
from .contracts import EventType, StageStatusPayload, SseEnvelope, validate_event_payload

_KEEPALIVE_SECONDS = 20.0
_STOP = object()


def build_event_id(session_id: str, turn_id: str, seq: int) -> str:
    return "{session}:{turn}:{seq}".format(session=session_id, turn=turn_id, seq=seq)


def serialize_envelope(envelope: SseEnvelope, seq: int) -> str:
    validated = envelope.model_copy(
        update={"payload": validate_event_payload(envelope.event_type, envelope.payload)}
    )
    body = validated.model_dump(mode="json")
    lines = [
        "id: {event_id}".format(
            event_id=build_event_id(validated.session_id, validated.turn_id, seq),
        ),
        "event: {event_type}".format(event_type=validated.event_type),
        "data: {payload}".format(
            payload=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        ),
        "",
        "",
    ]
    return "\n".join(lines)


def stream_envelopes(
    events: Iterable[SseEnvelope],
    *,
    keepalive_seconds: float = _KEEPALIVE_SECONDS,
) -> Iterator[str]:
    yield from _stream_envelopes_with_keepalive(events, keepalive_seconds=keepalive_seconds)


def _stream_envelopes_with_keepalive(
    events: Iterable[SseEnvelope],
    *,
    keepalive_seconds: float,
) -> Iterator[str]:
    if keepalive_seconds <= 0:
        for index, envelope in enumerate(events, start=1):
            yield serialize_envelope(envelope, seq=index)
        return

    event_queue: "queue.Queue[object]" = queue.Queue()
    worker_error: list[BaseException] = []

    def _pump_events() -> None:
        try:
            for envelope in events:
                event_queue.put(envelope)
        except BaseException as exc:  # pragma: no cover - defensive safeguard
            worker_error.append(exc)
        finally:
            event_queue.put(_STOP)

    threading.Thread(target=_pump_events, name="sse-stream-pump", daemon=True).start()

    seq = 0
    last_envelope: SseEnvelope | None = None
    while True:
        try:
            item = event_queue.get(timeout=keepalive_seconds)
        except queue.Empty:
            if last_envelope is None:
                continue
            seq += 1
            yield serialize_envelope(_build_keepalive_envelope(last_envelope), seq=seq)
            continue

        if item is _STOP:
            break

        if not isinstance(item, SseEnvelope):  # pragma: no cover - defensive safeguard
            continue

        last_envelope = item
        seq += 1
        yield serialize_envelope(item, seq=seq)

    if worker_error:
        raise worker_error[0]


def _build_keepalive_envelope(template: SseEnvelope) -> SseEnvelope:
    now = datetime.now(timezone.utc)
    return SseEnvelope(
        event_type=EventType.HEARTBEAT.value,
        trace_id=template.trace_id,
        session_id=template.session_id,
        turn_id=template.turn_id,
        timestamp=now,
        workflow_version=template.workflow_version,
        payload=StageStatusPayload(
            stage="stream_keepalive",
            status="running",
            elapsed_ms=None,
            degrade_to=None,
            error=None,
            current_stage="stream_keepalive",
            stage_status="running",
            route_reason="stream_keepalive",
            message="processing",
        ).model_dump(mode="json"),
    )


def build_sse_response(events: Iterable[SseEnvelope]) -> StreamingResponse:
    return StreamingResponse(
        stream_envelopes(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
