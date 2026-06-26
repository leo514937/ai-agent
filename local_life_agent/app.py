"""FastAPI HTTP wrapper for the local life agent runtime.

Provides endpoints for health check, streaming chat, feedback, approval,
and session state inspection as expected by the Java backend.
"""

from __future__ import annotations

import nest_asyncio
nest_asyncio.apply()

import json
from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from local_life_agent.agent import run_agent_graph
from local_life_agent.observability.file_logger import get_python_service_logger
from local_life_agent.session.store import get_session_store

app = FastAPI(title="Local Life Agent Service", version="1.0.0")
_FILE_LOGGER = get_python_service_logger()


class ChatRequest(BaseModel):
    user_id: str = Field(default="guest")
    session_id: str = Field(default="")
    trace_id: str = Field(default="")
    turn_id: str = Field(default="")
    page: str = Field(default="assistant")
    message: str = Field(default="")
    response_mode: str = Field(default="default")
    topic_hint: str = Field(default="")
    history_summary: str = Field(default="")
    client_context: dict[str, Any] = Field(default_factory=dict)


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
    _FILE_LOGGER.info(
        "chat_stream_request session_id=%s trace_id=%s turn_id=%s page=%s message=%s",
        request.session_id or "",
        request.trace_id or "",
        request.turn_id or "",
        request.page or "",
        request.message or "",
    )
    response = run_agent_graph(request.message, session_id=request.session_id)
    
    trace_id = response.trace_id or request.trace_id or "trace-anon"
    session_id = response.session_id or request.session_id or "session-anon"
    turn_id = request.turn_id or "turn-anon"
    
    def event_stream():
        # 1. Emit trace_started
        yield f"event: trace_started\ndata: {json.dumps({'event_type': 'trace_started', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'workflow_version': 'hm-dianping-python/v1'}}, ensure_ascii=False)}\n\n"
        
        # 2. Emit input_normalized
        yield f"event: input_normalized\ndata: {json.dumps({'event_type': 'input_normalized', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'normalized_text': request.message, 'input_type': 'text'}}, ensure_ascii=False)}\n\n"
        
        # 3. Process execution trace from agent debug info to output intermediate steps
        if response.debug:
            for log_entry in response.debug.execution_trace:
                node_name = log_entry.get("node")
                status = log_entry.get("status")
                
                # Emit events based on execution nodes
                if node_name == "top_intent_router":
                    intent_val = log_entry.get("metadata", {}).get("intent", "local_life")
                    yield f"event: intent_detected\ndata: {json.dumps({'event_type': 'intent_detected', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'top_intent': intent_val, 'confidence': 1.0}}, ensure_ascii=False)}\n\n"
                
                elif node_name == "semantic_parse":
                    yield f"event: semantic_frame_ready\ndata: {json.dumps({'event_type': 'semantic_frame_ready', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'top_intent': log_entry.get('metadata', {}).get('top_intent', 'local_life'), 'task_type': log_entry.get('metadata', {}).get('task_type', '')}}, ensure_ascii=False)}\n\n"
                
                elif node_name == "tool_execute":
                    # Emit simulated tool started/finished events
                    tool_calls = response.debug.tool_results or {}
                    for call_id, tool_res in tool_calls.items():
                        tool_name = tool_res.get("tool_name", "tool")
                        yield f"event: tool_call_started\ndata: {json.dumps({'event_type': 'tool_call_started', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'call_id': call_id, 'tool_name': tool_name}}, ensure_ascii=False)}\n\n"
                        yield f"event: tool_call_finished\ndata: {json.dumps({'event_type': 'tool_call_finished', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': {'call_id': call_id, 'tool_name': tool_name, 'status': tool_res.get('status', 'ok')}}, ensure_ascii=False)}\n\n"
        
        # 4. Emit final event
        final_payload = {
            "answer_text": response.answer_text,
            "mode": "remote",
            "source": "learning-agent-service",
            "page": request.page,
            "current_topic": "local_life",
            "fallback": False,
            "suggested_replies": [],
            "shops": response.cards or [],
            "vouchers": [],
            "cards": response.cards or [],
            "next_steps": [],
            "task_chain": []
        }
        _FILE_LOGGER.info(
            "chat_stream_final trace_id=%s session_id=%s answer=%s shops=%s",
            trace_id,
            session_id,
            response.answer_text,
            len(response.cards or []),
        )
        yield f"event: final\ndata: {json.dumps({'event_type': 'final', 'trace_id': trace_id, 'session_id': session_id, 'turn_id': turn_id, 'payload': final_payload}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/internal/v1/feedback/report")
async def report_feedback(request: Request):
    return {"status": "ok"}


@app.post("/internal/v1/approval/submit")
async def submit_approval(request: Request):
    return {"status": "ok"}


@app.get("/internal/v1/session/{session_id}/state")
async def get_session_state(session_id: str):
    store = get_session_store()
    state = store.load(session_id)
    return state.model_dump() if hasattr(state, "model_dump") else {}
