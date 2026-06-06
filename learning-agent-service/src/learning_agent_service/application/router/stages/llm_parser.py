from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from typing import Any

from ....domain.contracts import PersistentSessionContext
from .llm_prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .types import LLMParserResult, LLMTargetShop, SignalPolicyResult

_LOGGER = logging.getLogger(__name__)

def _local_parse_json_response(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if text is None:
        output = getattr(response, "output", None)
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, Mapping):
                            piece = part.get("text") or part.get("output_text") or part.get("value")
                        else:
                            piece = getattr(part, "text", None) or getattr(part, "output_text", None) or getattr(part, "value", None)
                        if piece:
                            chunks.append(str(piece))
                elif content:
                    chunks.append(str(content))
            text = "".join(chunks)
        elif output is not None:
            text = str(output)
        else:
            text = ""
    cleaned = str(text or "").strip()
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

def parse_query_with_llm(
    raw_query: str,
    persistent: PersistentSessionContext,
    signal_result: SignalPolicyResult,
    model_gateway: Any | None = None,
) -> LLMParserResult:
    # Attempt to call LLM if model_gateway is available
    if model_gateway is not None and hasattr(model_gateway, "runtime"):
        client = getattr(model_gateway.runtime, "client", None)
        default_model = getattr(model_gateway.runtime, "default_model", None)
        responses = getattr(client, "responses", None) if client is not None else None
        
        if responses is not None and hasattr(responses, "create"):
            candidates_json = json.dumps(
                [
                    {
                        "intent_name": c.intent_name,
                        "confidence": c.confidence,
                        "route": c.route,
                        "matched_signal": c.matched_signal,
                    }
                    for c in signal_result.candidates
                ],
                ensure_ascii=False,
            )
            merchant_hint = signal_result.merchant_hit.merchant_name if signal_result.merchant_hit else "无"
            pronoun_hint = signal_result.pronoun_hit.pronoun if signal_result.pronoun_hit else "无"
            
            last_intent = persistent.current_action or "None"
            current_shop = persistent.current_shop or "None"
            selected_shops = persistent.selected_shop_name or "None"
            slots_str = json.dumps(persistent.current_constraints, ensure_ascii=False)
            
            user_prompt = USER_PROMPT_TEMPLATE.format(
                candidates_json=candidates_json,
                merchant_hint=merchant_hint,
                pronoun_hint=pronoun_hint,
                last_intent=last_intent,
                current_shop=current_shop,
                selected_shops=selected_shops,
                slots=slots_str,
                raw_query=raw_query,
            )
            
            def _call_llm() -> Any:
                return responses.create(
                    model=default_model or model_gateway.runtime.default_model,
                    input=[
                        {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                    ],
                    temperature=0,
                    max_output_tokens=300,
                )
                
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_call_llm)
                    response = future.result(timeout=1.5)
                    
                payload = _local_parse_json_response(response)
                
                target_shop_data = payload.get("target_shop") or {}
                target_shop = None
                if target_shop_data:
                    target_shop = LLMTargetShop(
                        shop_name=target_shop_data.get("shop_name"),
                        reference_type=target_shop_data.get("reference_type", "none"),
                        clarify_if_missing=bool(target_shop_data.get("clarify_if_missing", False)),
                    )
                    
                return LLMParserResult(
                    intent=payload.get("intent", "chit_chat"),
                    confidence=float(payload.get("confidence", 0.0) or 0.0),
                    slots=payload.get("slots", {}),
                    facet_needs=payload.get("facet_needs", []),
                    needs_rag=bool(payload.get("needs_rag", False)),
                    needs_tool=bool(payload.get("needs_tool", False)),
                    needs_clarify=bool(payload.get("needs_clarify", False)),
                    target_shop=target_shop,
                    reason=payload.get("reason", ""),
                    raw_llm_output=payload,
                )
            except Exception as e:
                _LOGGER.warning(f"Stage 3 LLM Parser call failed or timed out: {e}. Falling back to heuristics.")

    # Rule-based / Heuristic Fallback
    from ...routing_signals.base import route_semantic_query
    draft = route_semantic_query(raw_query, persistent=persistent)

    target_shop = None
    if signal_result.merchant_hit:
        target_shop = LLMTargetShop(
            shop_name=signal_result.merchant_hit.merchant_name,
            reference_type="explicit",
            clarify_if_missing=False,
        )
    elif signal_result.pronoun_hit:
        target_shop = LLMTargetShop(
            shop_name=None,
            reference_type="pronoun_inherit",
            clarify_if_missing=False,
        )

    return LLMParserResult(
        intent=draft.intent,
        confidence=draft.confidence,
        slots=dict(draft.slots or {}),
        facet_needs=list(draft.preferred_chunk_roles or []),
        needs_rag=draft.should_retrieve,
        needs_tool=draft.should_call_tool,
        needs_clarify=draft.required_action == "clarify",
        target_shop=target_shop,
        reason=draft.route_reason or "rule_based_fallback",
        missing_slots=list(draft.missing_slots or []),
    )
