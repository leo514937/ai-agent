from __future__ import annotations

import json
import os
from typing import Any, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field
import httpx

class ChatStreamResult(BaseModel):
    final_answer: str = ""
    delta_text: str = ""
    final_payload: dict = Field(default_factory=dict)
    final_context: dict = Field(default_factory=dict)
    events: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    retrieval_events: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    error_events: list[dict] = Field(default_factory=list)

class ChatStreamTestClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.getenv("LEARNING_AGENT_REAL_STREAM_URL", "http://127.0.0.1:8000/internal/v1/chat/stream")
        # Explicitly set trust_env=False to avoid corporate/system local proxy settings (like verge-mihomo) 
        # from intercepting requests to localhost and causing random 502 Bad Gateway errors.
        self.client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False)
        self.token = os.getenv("LEARNING_AGENT_INTERNAL_API_TOKEN", "local-learning-agent-token")

    def post_message(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        extra_payload: dict | None = None,
    ) -> ChatStreamResult:
        effective_user_id = user_id or f"test-user-{session_id}"
        if "8000" in self.base_url or "internal" in self.base_url:
            turn_id = f"turn-{uuid4().hex[:12]}"
            trace_id = f"trace-{uuid4().hex[:12]}"
            context_payload = extra_payload or {}
            payload = {
                "message": message,
                "user_id": effective_user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_id": trace_id,
                "page": "assistant",
                "context": context_payload,
                "client_context": context_payload,
            }
            headers = {
                "Accept": "text/event-stream",
                "Connection": "close",
                "X-Internal-Token": self.token,
            }
        else:
            payload = {
                "message": message,
                "sessionId": session_id,
                "userId": effective_user_id,
            }
            if extra_payload:
                payload.update(extra_payload)
            headers = {
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            }

        # SSE decoding helper
        events: list[dict[str, Any]] = []
        raw_parts: list[str] = []
        status_code: int | None = None

        with self.client.stream(
            "POST",
            self.base_url,
            json=payload,
            headers=headers,
        ) as response:
            status_code = response.status_code
            if status_code != 200:
                # Capture and output the error body for immediate diagnostic visibility in Harness Engineering.
                try:
                    error_body = response.read().decode("utf-8")
                except Exception:
                    error_body = "<failed to read error body>"
                raise httpx.HTTPStatusError(
                    f"Unexpected status code {status_code}. Response body:\n{error_body}",
                    request=response.request,
                    response=response
                )
            for chunk in response.iter_text():
                if chunk:
                    raw_parts.append(chunk)

        raw_text = "".join(raw_parts)
        
        # Decode SSE events
        for block in raw_text.replace("\r\n", "\n").strip().split("\n\n"):
            if not block.strip():
                continue
            event_type = "message"
            data_lines: list[str] = []
            for line in block.splitlines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
            data_raw = "\n".join(data_lines).strip()
            data: Any = None
            if data_raw:
                try:
                    data = json.loads(data_raw)
                except Exception:
                    data = data_raw
            events.append({"event_type": event_type, "data": data})

        # Parse SSE events into ChatStreamResult
        result = ChatStreamResult()
        result.events = events

        for event in events:
            etype = event.get("event_type")
            edata = event.get("data")
            
            payload_data = {}
            if isinstance(edata, dict):
                payload_data = edata.get("payload") or edata if isinstance(edata.get("payload"), dict) else edata

            if etype == "delta":
                if isinstance(payload_data, dict) and "text" in payload_data:
                    result.delta_text += str(payload_data["text"])
                elif isinstance(payload_data, str):
                    result.delta_text += payload_data
            elif etype == "tool_call":
                result.tool_calls.append(payload_data)
            elif etype == "tool_result":
                result.tool_results.append(payload_data)
            elif etype == "retrieval_result":
                result.retrieval_events.append(payload_data)
            elif etype == "error":
                result.error_events.append(payload_data)
            elif etype == "final":
                if isinstance(payload_data, dict):
                    result.final_answer = payload_data.get("answer_text") or payload_data.get("final_answer") or ""
                    result.metrics = payload_data.get("metrics") or {}
                    result.final_payload = payload_data
                    result.final_context = payload_data.get("context") or {}

        # Fallback if final answer was not parsed from a "final" event but is present in metrics/context
        if not result.final_answer:
            for event in events:
                if event.get("event_type") == "final":
                    edata = event.get("data") or {}
                    if isinstance(edata, dict):
                        result.final_answer = edata.get("answer_text") or ""
                        result.metrics = edata.get("metrics") or {}
                        result.final_payload = edata
                        result.final_context = edata.get("context") or {}

        return result
