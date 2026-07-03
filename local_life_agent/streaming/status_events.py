from __future__ import annotations

import json
from typing import Any

from .events import (
    StreamEventEnvelope,
    make_evidence_update,
    make_fallback,
    make_final,
    make_preview,
    make_status,
    make_trace_started,
)


def to_sse_block(event: StreamEventEnvelope) -> str:
    payload = event.model_dump(mode="json")
    return f"event: {event.event_type.value}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def make_status_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    status: str,
    *,
    stage: str | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    return to_sse_block(make_status(trace_id, session_id, turn_id, status, stage=stage, detail=detail))


def make_preview_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    text: str,
    *,
    verified: bool = False,
    preview_kind: str = "fast_preview",
    source: str | None = None,
) -> str:
    return to_sse_block(
        make_preview(
            trace_id,
            session_id,
            turn_id,
            text,
            verified=verified,
            preview_kind=preview_kind,
            source=source,
        )
    )


def make_trace_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    workflow_version: str,
    *,
    page: str | None = None,
    user_id: str | None = None,
) -> str:
    return to_sse_block(
        make_trace_started(
            trace_id,
            session_id,
            turn_id,
            workflow_version,
            page=page,
            user_id=user_id,
        )
    )


def make_fallback_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    reason: str,
    *,
    message: str | None = None,
) -> str:
    return to_sse_block(make_fallback(trace_id, session_id, turn_id, reason, message=message))


def make_final_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    answer_text: str,
    *,
    cards: list[dict[str, Any]] | None = None,
    next_steps: list[str] | None = None,
    verified: bool = True,
) -> str:
    return to_sse_block(
        make_final(
            trace_id,
            session_id,
            turn_id,
            answer_text,
            cards=cards,
            next_steps=next_steps,
            verified=verified,
        )
    )


def make_evidence_update_block(
    trace_id: str,
    session_id: str,
    turn_id: str,
    *,
    evidence_items: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    cache_key: str | None = None,
    cache_hit: bool | None = None,
) -> str:
    return to_sse_block(
        make_evidence_update(
            trace_id,
            session_id,
            turn_id,
            evidence_items=evidence_items,
            summary=summary,
            cache_key=cache_key,
            cache_hit=cache_hit,
        )
    )
