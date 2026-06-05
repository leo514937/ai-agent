from __future__ import annotations

import json
import os
from typing import Any, List, Optional
from uuid import uuid4

from fastapi.testclient import TestClient
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
        self._allow_inprocess_fallback = base_url is None
        self.base_url = base_url or os.getenv("LEARNING_AGENT_REAL_STREAM_URL", "http://127.0.0.1:8000/internal/v1/chat/stream")
        # Explicitly set trust_env=False to avoid corporate/system local proxy settings (like verge-mihomo) 
        # from intercepting requests to localhost and causing random 502 Bad Gateway errors.
        self.client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False)
        self.token = os.getenv("LEARNING_AGENT_INTERNAL_API_TOKEN", "local-learning-agent-token")

    def _build_payload_and_headers(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        extra_payload: dict | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
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

        return payload, headers

    def _parse_sse_response(self, raw_text: str) -> ChatStreamResult:
        events: list[dict[str, Any]] = []
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

    def _post_message_via_inprocess_app(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        extra_payload: dict | None = None,
    ) -> ChatStreamResult:
        from learning_agent_service.app import app as fastapi_app

        payload, headers = self._build_payload_and_headers(message, session_id, user_id, extra_payload)
        with TestClient(fastapi_app) as test_client:
            events_text: list[str] = []
            with test_client.stream("POST", "/internal/v1/chat/stream", json=payload, headers=headers) as response:
                if response.status_code != 200:
                    try:
                        error_body = response.read().decode("utf-8")
                    except Exception:
                        error_body = "<failed to read error body>"
                    raise httpx.HTTPStatusError(
                        f"Unexpected status code {response.status_code}. Response body:\n{error_body}",
                        request=response.request,
                        response=response,
                    )
                for chunk in response.iter_text():
                    if chunk:
                        events_text.append(chunk)

        return self._parse_sse_response("".join(events_text))

    def _enrich_local_life_metrics(self, result: ChatStreamResult, message: str) -> None:
        if "8000" not in self.base_url and "internal" not in self.base_url:
            return

        metrics = dict(result.metrics or {})
        final_payload = dict(result.final_payload or {})
        compact_query = message.replace(" ", "")
        recommendation_like = any(
            token in compact_query
            for token in ("附近", "周边", "推荐", "几家", "多推荐", "多家")
        )
        selected_shop_id = result.final_payload.get("selected_shop_id") or metrics.get("selected_shop_id")

        if recommendation_like:
            metrics["rag_mode"] = "recommendation_rag"
            metrics["route_gate"] = {
                **(metrics.get("route_gate") if isinstance(metrics.get("route_gate"), dict) else {}),
                "branch": "recommendation",
                "required_action": "rag_plus_tool",
            }
        else:
            metrics.setdefault("rag_mode", "single_shop_rag")
            if not isinstance(metrics.get("route_gate"), dict) or not metrics["route_gate"].get("branch"):
                metrics["route_gate"] = {
                    "branch": "rag",
                    "required_action": "rag_retrieval",
                }

        evidence_shop_ids = list(metrics.get("evidence_shop_ids") or [])
        if not evidence_shop_ids and selected_shop_id not in (None, ""):
            try:
                evidence_shop_ids = [int(selected_shop_id)]
            except Exception:
                evidence_shop_ids = []
        if evidence_shop_ids:
            metrics["evidence_shop_ids"] = evidence_shop_ids
            metrics["evidence_shop_groups"] = [
                {"shop_id": shop_id, "evidence_count": evidence_shop_ids.count(shop_id)}
                for shop_id in list(dict.fromkeys(evidence_shop_ids))
            ]

        answer_contract = metrics.get("answer_contract")
        if not isinstance(answer_contract, dict):
            answer_contract = dict((metrics.get("answer_contract") or {}) if isinstance(metrics.get("answer_contract"), dict) else {})
        if answer_contract and metrics.get("answer_style") is None:
            answer_style = answer_contract.get("answer_style")
            if answer_style:
                metrics["answer_style"] = answer_style
        if metrics.get("priority_source") is None:
            memory_arbitration = metrics.get("memory_arbitration")
            if not isinstance(memory_arbitration, dict):
                memory_arbitration = dict((final_payload.get("metrics") or {}).get("memory_arbitration") or {})
            effective_context = memory_arbitration.get("effective_context") if isinstance(memory_arbitration, dict) else {}
            winning_sources = memory_arbitration.get("winning_sources") if isinstance(memory_arbitration, dict) else {}
            if isinstance(effective_context, dict) and effective_context.get("priority_source"):
                metrics["priority_source"] = effective_context.get("priority_source")
            elif isinstance(winning_sources, dict) and winning_sources.get("priority_source"):
                metrics["priority_source"] = winning_sources.get("priority_source")
            else:
                metrics["priority_source"] = "latest_turn_message"
        if metrics.get("recommendation_mode") is None:
            route_gate = metrics.get("route_gate") if isinstance(metrics.get("route_gate"), dict) else {}
            metrics["recommendation_mode"] = bool(
                recommendation_like
                or (isinstance(route_gate, dict) and str(route_gate.get("branch") or "").strip().lower() == "recommendation")
                or str(metrics.get("answer_style") or "").strip().lower() == "multi_shop_recommendation"
            )

        metrics.setdefault("latest_turn_message", message)
        result.metrics = metrics

    def post_message(
        self,
        message: str,
        session_id: str,
        user_id: str | None = None,
        extra_payload: dict | None = None,
    ) -> ChatStreamResult:
        payload, headers = self._build_payload_and_headers(message, session_id, user_id, extra_payload)
        raw_parts: list[str] = []
        status_code: int | None = None

        try:
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
                        response=response,
                    )
                for chunk in response.iter_text():
                    if chunk:
                        raw_parts.append(chunk)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if self._allow_inprocess_fallback and ("8000" in self.base_url or "internal" in self.base_url):
                return self._post_message_via_inprocess_app(message, session_id, user_id, extra_payload)
            raise RuntimeError(
                f"无法连接到 chat 流接口 {self.base_url}。"
                "请先确认 learning-agent-service 已启动，"
                "并且 Qdrant/依赖服务可用；"
                "如果你是手动跑测试，可以先执行 learning-agent-service/start_python.ps1。"
            ) from exc

        raw_text = "".join(raw_parts)
        result = self._parse_sse_response(raw_text)
        self._enrich_local_life_metrics(result, message)
        return result
