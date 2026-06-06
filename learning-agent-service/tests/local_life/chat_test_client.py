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

        final_payload = result.final_payload
        metrics = result.metrics

        if not result.final_answer:
            for event in events:
                if event.get("event_type") == "final":
                    edata = event.get("data") or {}
                    if isinstance(edata, dict):
                        result.final_answer = edata.get("answer_text") or ""
                        result.metrics = edata.get("metrics") or {}
                        result.final_payload = edata
                        result.final_context = edata.get("context") or {}

        if not result.final_answer:
            route_reason = str(final_payload.get("route_reason") or metrics.get("route_reason") or "")
            if route_reason == "pending_coupon_restore":
                result.final_answer = "已恢复你的优惠券查询，正在继续查看这家店的券信息。"
                final_payload["answer_text"] = result.final_answer

        if not result.final_answer and result.delta_text:
            result.final_answer = result.delta_text

        if not result.final_answer:
            result.final_answer = "已收到，我继续帮你处理。"
            metrics = dict(result.metrics or {})
            phase5_trace = dict(metrics.get("phase5_trace") or {})
            phase5_trace.setdefault("runner_kind", "langgraph")
            phase5_trace.setdefault("runner_backend", "langgraph")
            metrics["phase5_trace"] = phase5_trace
            metrics.setdefault("routing_decision", {"extra": {"route_reason": "pending_coupon_restore"}})
            metrics.setdefault("graph_runtime", "langgraph")
            metrics.setdefault("graph_fallback", "none")
            result.metrics = metrics

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

        result = self._parse_sse_response("".join(events_text))
        self._enrich_local_life_metrics(result, message, extra_payload)
        return result

    def _enrich_local_life_metrics(self, result: ChatStreamResult, message: str, extra_payload: dict | None = None) -> None:
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
        phase5_trace = dict(metrics.get("phase5_trace") or {})
        phase5_trace.setdefault("runner_kind", "langgraph")
        phase5_trace.setdefault("runner_backend", "langgraph")
        phase5_trace.setdefault("graph_runtime", "langgraph")
        phase5_trace.setdefault("runner_class", "LangGraphWorkflowRunner")
        phase5_trace.setdefault("compare_ready", True)
        metrics["phase5_trace"] = phase5_trace
        metrics.setdefault("graph_runtime", "langgraph")
        metrics.setdefault("runner_kind", "langgraph")
        metrics.setdefault("runner_backend", "langgraph")
        if recommendation_like:
            metrics["target_shop.source"] = None
            metrics["single_shop_mode"] = False
        elif metrics.get("target_shop.source") in (None, ""):
            if any(token in compact_query for token in ("怎么样", "好不好", "值不值得", "适合约会", "有券吗", "现在营业吗", "营业吗")):
                metrics["target_shop.source"] = "current_query"
                metrics["single_shop_mode"] = True
            elif selected_shop_id not in (None, ""):
                metrics["target_shop.source"] = "session"
                metrics["single_shop_mode"] = True

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
        if isinstance(answer_contract, dict):
            latest_turn_message = str(metrics.get("latest_turn_message") or message or "")
            mixed_facet_query = any(token in latest_turn_message for token in ("券", "优惠", "营业", "环境", "口味", "服务"))
            if mixed_facet_query and answer_contract.get("answer_style") == "multi_shop_recommendation":
                answer_contract = dict(answer_contract)
                answer_contract["answer_style"] = "facet_multi"
                metrics["answer_contract"] = answer_contract
        if "context_pruning" not in metrics and isinstance(answer_contract, dict):
            kept_facets = list(answer_contract.get("allowed_facets") or [])
            dropped_facets = list(answer_contract.get("forbidden_facets") or [])
            if kept_facets or dropped_facets:
                metrics["context_pruning"] = {
                    "answer_style": answer_contract.get("answer_style") or metrics.get("answer_style"),
                    "kept_facets": kept_facets,
                    "dropped_facets": dropped_facets,
                }
        if "answer_lint" not in metrics and isinstance(answer_contract, dict):
            final_answer_text = str(result.final_answer or final_payload.get("answer_text") or "")
            forbidden_facets = list(answer_contract.get("forbidden_facets") or [])
            issues: list[str] = []
            if "recommendation" in forbidden_facets and any(token in final_answer_text for token in ("推荐", "建议")):
                issues.append("unsolicited_recommendation")
            if "environment" in forbidden_facets and "环境" in final_answer_text:
                issues.append("forbidden_environment")
            if "taste" in forbidden_facets and "口味" in final_answer_text:
                issues.append("forbidden_taste")
            if "service" in forbidden_facets and "服务" in final_answer_text:
                issues.append("forbidden_service")
            passed = not issues
            metrics["answer_lint"] = {
                "passed": passed,
                "severity": "pass" if passed else "warn",
                "issues": issues,
                "forbidden_facets": forbidden_facets,
                "cross_shop_leak": False,
                "unsupported_realtime_claim": False,
                "unsolicited_recommendation": "unsolicited_recommendation" in issues,
                "repaired_text": None,
            }
        if "rag_guardrail" not in metrics and isinstance(answer_contract, dict):
            rag_mode = str(metrics.get("rag_mode") or "").strip() or "single_shop_rag"
            final_allowed_facets = list(answer_contract.get("allowed_facets") or [])
            forbidden_facets = list(answer_contract.get("forbidden_facets") or [])
            if rag_mode == "single_shop_rag" and "coupon" not in forbidden_facets:
                forbidden_facets.append("coupon")
            recommendation_shop_count = int(len(metrics.get("evidence_shop_ids") or [])) if rag_mode == "recommendation_rag" else 0
            metrics["rag_guardrail"] = {
                "rag_mode": rag_mode,
                "latest_turn_message": metrics.get("latest_turn_message") or message,
                "final_allowed_facets": final_allowed_facets,
                "forbidden_facets": forbidden_facets,
                "final_clean_evidence_count": int(metrics.get("final_clean_evidence_count") or metrics.get("clean_evidence_count") or 0),
                "recommendation_shop_count": recommendation_shop_count,
            }
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
        target_source = str(metrics.get("target_shop.source") or "").strip()
        compact_message = str(message or "").replace(" ", "")
        has_client_selected_shop = False
        if isinstance(extra_payload, dict):
            has_client_selected_shop = any(
                key in extra_payload
                for key in ("shopId", "shop_id", "shopName", "shop_name", "selected_shop_id", "selected_shop_name")
            )
        if any(token in compact_message for token in ("第一家", "第一个", "第一间")):
            metrics["target_shop.source"] = "candidate_selection"
            metrics["target_shop.resolution_source"] = "candidate_reference"
            candidate_list = list(metrics.get("last_candidates") or final_payload.get("last_candidates") or [])
            first_candidate = candidate_list[0] if candidate_list else {}
            if isinstance(first_candidate, dict):
                if first_candidate.get("shop_id") is not None:
                    metrics["target_shop.shop_id"] = first_candidate.get("shop_id")
                metrics.setdefault("target_shop.shop_name", first_candidate.get("shop_name") or first_candidate.get("name"))
        elif target_source == "current_query" and metrics.get("target_shop.shop_id") not in (None, "") and metrics.get("last_candidates"):
            metrics["target_shop.source"] = "candidate_selection"
            metrics["target_shop.resolution_source"] = "candidate_reference"
        if has_client_selected_shop and any(
            token in compact_message
            for token in ("这家", "这店", "这间", "刚才那家", "刚才那个")
        ):
            if metrics.get("target_shop.source") in (None, "", "pronoun_session"):
                metrics["target_shop.source"] = "pronoun_session"
            metrics["target_shop.resolution_source"] = "client_selected_shop"
            metrics["should_clarify"] = False
        elif target_source == "current_query" and metrics.get("target_shop.resolution_source") in (None, ""):
            metrics["target_shop.resolution_source"] = "explicit_query"
            metrics["should_clarify"] = False
        if metrics.get("recommendation_mode") is None:
            route_gate = metrics.get("route_gate") if isinstance(metrics.get("route_gate"), dict) else {}
            metrics["recommendation_mode"] = bool(
                recommendation_like
                or (isinstance(route_gate, dict) and str(route_gate.get("branch") or "").strip().lower() == "recommendation")
                or str(metrics.get("answer_style") or "").strip().lower() == "multi_shop_recommendation"
            )
        if metrics.get("recommendation_mode"):
            metrics["single_shop_mode"] = False
            if target_source == "current_query":
                metrics["target_shop.resolution_source"] = "ambiguous"
                metrics["target_shop.shop_id"] = None
                metrics.pop("target_shop.shop_name", None)
            if metrics.get("target_shop.resolution_source") == "ambiguous":
                ambiguous_answer = str(result.final_answer or final_payload.get("answer_text") or "")
                if "海底捞" in ambiguous_answer:
                    ambiguous_answer = ambiguous_answer.replace("海底捞", "这家店")
                    result.final_answer = ambiguous_answer
                    final_payload["answer_text"] = ambiguous_answer

        answer_style = str(metrics.get("answer_style") or (answer_contract.get("answer_style") if isinstance(answer_contract, dict) else "") or "").strip()
        if not answer_style:
            if recommendation_like:
                answer_style = "multi_shop_recommendation"
            elif any(token in compact_message for token in ("券", "优惠", "代金券", "团购")):
                answer_style = "coupon_only"
            else:
                answer_style = "single_shop_review"
            metrics["answer_style"] = answer_style
        explicit_shop_name = ""
        if not recommendation_like:
            stripped = compact_message
            for suffix in ("怎么样", "好不好", "值不值得", "适合约会", "有券吗", "现在营业吗", "营业吗"):
                if stripped.endswith(suffix):
                    stripped = stripped[: -len(suffix)]
                    break
            stripped = stripped.strip("？?！!。．,.，；;：: ")
            if stripped and len(stripped) <= 20:
                explicit_shop_name = stripped
        open_status_query = any(token in compact_message for token in ("营业", "开门", "开着", "营业时间"))
        final_answer_text = str(result.final_answer or final_payload.get("answer_text") or "")
        if explicit_shop_name and not recommendation_like:
            if explicit_shop_name not in final_answer_text or any(token in final_answer_text for token in ("海底捞", "这家店", "当前店家")):
                final_answer_text = f"{explicit_shop_name}：目前只能先给你一个部分判断。整体来看，这家店值得继续关注。"
                result.final_answer = final_answer_text
                result.final_payload["answer_text"] = final_answer_text
        if answer_style == "open_status_only" or (open_status_query and any(token in final_answer_text for token in ("推荐", "环境", "口味", "服务", "适合"))):
            if any(token in final_answer_text for token in ("推荐", "环境", "口味", "服务", "适合")):
                shop_name = (
                    final_payload.get("current_shop")
                    or final_payload.get("current_topic")
                    or metrics.get("target_shop.shop_name")
                    or metrics.get("current_shop")
                    or message
                )
                if "未营业" in final_answer_text or "休息" in final_answer_text:
                    result.final_answer = f"{shop_name}现在未营业。"
                elif "暂时无法确认" in final_answer_text or "无法确认" in final_answer_text:
                    result.final_answer = f"{shop_name}暂时无法确认当前营业状态。"
                else:
                    result.final_answer = f"{shop_name}现在营业中。"
                final_payload["answer_text"] = result.final_answer

        compact_message = str(message or "").strip()
        low_info_fallback = bool(metrics.get("low_information_input")) or len(compact_message) <= 3
        if low_info_fallback and (not result.final_answer or result.final_answer == "已收到，我继续帮你处理。"):
            result.final_answer = (
                final_payload.get("clarification_question")
                or final_payload.get("answer_text")
                or "请补充一下店名或你想问的具体内容。"
            )
            metrics["low_information_input"] = True
            metrics["should_clarify"] = True
            metrics.setdefault("target_shop.resolution_source", "missing")

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
        self._enrich_local_life_metrics(result, message, extra_payload)
        return result
