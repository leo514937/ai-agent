from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime

from .answer_planner import build_answer_planner_request, parse_answer_plan_payload
from .hybrid_router import HybridRouter, LLMRouteDecision


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    def walk(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
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
    return text or ""


def _extract_json_payload(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
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


@dataclass
class LocalLifeModelAssistant:
    runtime: OpenAIRuntime | None = None
    model: str = ""
    temperature: float = 0.0
    router: HybridRouter | None = None

    def __post_init__(self):
        if self.router is None:
            self.router = HybridRouter(runtime=self.runtime)

    @property
    def enabled(self) -> bool:
        return self.runtime is not None

    def route_query(
        self,
        query: str,
        *,
        session_context: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
        use_llm: bool = True,
    ) -> tuple[LLMRouteDecision, dict[str, Any]]:
        """使用HybridRouter进行路由决策"""
        if self.router is None:
            self.router = HybridRouter(runtime=self.runtime)

        decision, trace = self.router.route(
            query=query,
            session_context=session_context,
            client_context=client_context,
            use_llm=use_llm,
        )
        return decision, trace.to_log_dict()

    def suggest_understanding(
        self,
        *,
        raw_query: str,
        client_context: Mapping[str, Any] | None = None,
        session_context: Mapping[str, Any] | None = None,
        heuristic_summary: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = {
            "stage": "understanding",
            "raw_query": raw_query,
            "client_context": _as_mapping(client_context),
            "session_context": _as_mapping(session_context),
            "heuristic_summary": _as_mapping(heuristic_summary),
        }
        system_text = (
            "你是本地生活助手的理解层。"
            "请返回严格 JSON，字段必须优先覆盖 normalized_query、semantic_query、keyword_query、intent、decision、confidence、requested_output_style、slots。"
            "如果是本地生活问法，slots 里要尽量包含 domain、local_life_intent、tool_name、tool_input、city、category、shop_query、scene、preferences、avoid、companions、price、time、location。"
            "当信息不足时，再补 clarification_question 和 clarification_options。"
            "tool_input 必须是可直接传给工具的 JSON 对象，不要只给泛化描述。"
            "尽量给出便于检索和路由的结构化结果。"
        )
        return self._call_json(system_text=system_text, prompt=prompt, max_output_tokens=320)

    def suggest_response(
        self,
        *,
        raw_query: str,
        slots: Mapping[str, Any] | None = None,
        ranked_candidates: Sequence[Mapping[str, Any]] | None = None,
        evidence_claims: Sequence[Mapping[str, Any]] | None = None,
        evidence_pack: Mapping[str, Any] | None = None,
        clarification: Mapping[str, Any] | None = None,
        source_mode: str | None = None,
        degraded_reason: str | None = None,
        knowledge_freshness: Mapping[str, Any] | None = None,
        route_decision: str | None = None,
        route_reason: str | None = None,
        safety_result: Mapping[str, Any] | None = None,
        approval_required: bool = False,
        answer_contract: Any | None = None,
    ) -> dict[str, Any]:
        return self.compose_answer_plan(
            raw_query=raw_query,
            slots=slots,
            ranked_candidates=ranked_candidates,
            evidence_claims=evidence_claims,
            evidence_pack=evidence_pack,
            clarification=clarification,
            source_mode=source_mode,
            degraded_reason=degraded_reason,
            knowledge_freshness=knowledge_freshness,
            route_decision=route_decision,
            route_reason=route_reason,
            safety_result=safety_result,
            approval_required=approval_required,
            answer_contract=answer_contract,
        )

    def compose_answer_plan(
        self,
        *,
        raw_query: str,
        slots: Mapping[str, Any] | None = None,
        ranked_candidates: Sequence[Mapping[str, Any]] | None = None,
        evidence_claims: Sequence[Mapping[str, Any]] | None = None,
        evidence_pack: Mapping[str, Any] | None = None,
        clarification: Mapping[str, Any] | None = None,
        source_mode: str | None = None,
        degraded_reason: str | None = None,
        knowledge_freshness: Mapping[str, Any] | None = None,
        route_decision: str | None = None,
        route_reason: str | None = None,
        safety_result: Mapping[str, Any] | None = None,
        approval_required: bool = False,
        answer_contract: Any | None = None,
    ) -> dict[str, Any]:
        prompt = build_answer_planner_request(
            raw_query=raw_query,
            slots=_as_mapping(slots),
            ranked_candidates=[_as_mapping(item) for item in ranked_candidates or []],
            evidence_pack=evidence_pack,
            evidence_claims=[_as_mapping(item) for item in evidence_claims or []] or None,
            safety_result=_as_mapping(safety_result),
            source_mode=source_mode,
            degraded_reason=degraded_reason,
            knowledge_freshness=_as_mapping(knowledge_freshness),
            route_decision=route_decision,
            route_reason=route_reason,
            clarification=_as_mapping(clarification),
            approval_required=approval_required,
            answer_contract=answer_contract,
        )
        if evidence_claims:
            prompt["evidence_claims"] = [_as_mapping(item) for item in evidence_claims]
        system_text = (
            "你是本地生活决策生成器。"
            "你只能基于 EvidencePack、ranked_candidates、slots、safety_result 回答。"
            "不得编造不存在的优惠券、评分、距离、营业时间、排队情况。"
            "如果证据不足，要说明“不确定”或“当前证据不足”。"
            "本地生活回答必须覆盖：结论、推荐理由、适合/不适合场景、风险点、优惠券建议、下一步动作。"
            "不同意图走不同策略：recommend 给 top 1 + 备选 2 家；compare 对比距离、价格、评分、环境、优惠、风险；"
            "shop_detail 围绕单店回答，强调适合谁、注意什么、是否值得去；coupon_advice 判断券是否值得，说明限制和风险；"
            "environment_check 重点回答安静、停车、排队、卫生、服务等体验因素；avoid_pit 重点输出坑点和规避建议；"
            "booking/order 必须遵守 safety_result 和 approval_required，不得直接替用户确认交易；clarification 信息不足时提出最小必要澄清。"
            "输出必须是严格 JSON，不要 markdown，不要代码块。"
            "evidence_used 必须引用 EvidencePack 中存在的 evidence_id。"
        )
        payload = self._call_json(system_text=system_text, prompt=prompt, max_output_tokens=640)
        if not payload:
            return {}
        if (
            not any(payload.get(key) for key in ("answer_text", "decision_type", "recommendation_summary"))
            and not payload.get("candidate_reasons")
            and not payload.get("evidence_used")
        ):
            return {}
        plan = parse_answer_plan_payload(payload)
        if plan is None:
            return {}
        return plan.model_dump(mode="json")

    def _call_json(self, *, system_text: str, prompt: Mapping[str, Any], max_output_tokens: int) -> dict[str, Any]:
        if self.runtime is None:
            return {}
        client = self.runtime.client
        responses = getattr(client, "responses", None)
        if responses is None or not hasattr(responses, "create"):
            return {}
        try:
            response = responses.create(
                model=self.model or self.runtime.default_model,
                input=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": system_text,
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}],
                    },
                ],
                temperature=self.temperature,
                max_output_tokens=max_output_tokens,
            )
        except Exception:
            return {}
        payload = _extract_json_payload(_extract_response_text(response))
        return payload if isinstance(payload, dict) else {}
