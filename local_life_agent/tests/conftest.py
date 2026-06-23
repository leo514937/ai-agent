"""Shared test fixtures for graph-level LLM path verification."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest

# ── Force mock tool backend for all tests ──────────────────────────────
# Tests use mock data (shop IDs like shop_sc_01), not the real DB or
# Java API.  Override at the module level so every import path sees it.
import local_life_agent.config as _cfg
_cfg.TOOL_BACKEND = "mock"

LLM_SENTINEL_PREFIX = "LLM_SENTINEL_"


class SpyRealLLMBackend:
    """Stateful spy backend that behaves like a deterministic real LLM.

    The backend supports three graph entry points:
    - top intent routing
    - semantic frame parsing
    - LLM verbalization

    It records every request/response pair and injects a sentinel marker into
    raw output plus semantic-frame debug fields so tests can prove the graph
    really traversed the injected backend.
    """

    llm_backend = "spy_real_llm"

    def __init__(self, scenario_payloads: dict[str, dict[str, Any]] | None = None, **kwargs):
        self.requests: list[dict[str, Any]] = []
        self.prompts: list[str] = []
        self.responses: list[dict[str, Any]] = []
        self.sentinel_id = f"{LLM_SENTINEL_PREFIX}{uuid.uuid4().hex[:8].upper()}"
        self._scenario_payloads = dict(scenario_payloads or {})
        # Backward compat: default_payload= is stored as __default__ marker
        if kwargs.get("default_payload") is not None:
            self._scenario_payloads["__default__"] = kwargs["default_payload"]

    @property
    def called(self) -> bool:
        return bool(self.requests)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_request(self) -> dict[str, Any] | None:
        return self.requests[-1] if self.requests else None

    @property
    def last_response(self) -> dict[str, Any] | None:
        return self.responses[-1] if self.responses else None

    def reset(self) -> None:
        self.requests.clear()
        self.prompts.clear()
        self.responses.clear()

    def __call__(
        self,
        prompt: str = "",
        system_prompt: str = "",
        timeout_ms: int = 3000,
        **kwargs: Any,
    ) -> dict[str, Any]:
        request = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "timeout_ms": timeout_ms,
            "kwargs": kwargs,
        }
        self.requests.append(request)
        self.prompts.append(prompt)

        if "## DecisionPlan" in prompt:
            response = self._verbalizer_response(prompt, timeout_ms, kwargs)
        elif "# Top Intent Router" in prompt or "# 顶层意图路由" in prompt:
            response = self._top_intent_response(prompt, timeout_ms, kwargs)
        else:
            response = self._semantic_response(prompt, timeout_ms, kwargs)

        self.responses.append(response)
        return response

    def _extract_user_text(self, prompt: str) -> str:
        markers = ["User text:", "用户输入：", "用户输入:"]
        for marker in markers:
            if marker in prompt:
                return prompt.split(marker, 1)[1].strip().splitlines()[0].strip()
        return prompt.strip()

    def _top_intent_response(self, prompt: str, timeout_ms: int, kwargs: dict[str, Any]) -> dict[str, Any]:
        text = self._extract_user_text(prompt)
        payload = {
            "top_intent": "chat" if text in {"你好", "您好"} else "local_life",
            "confidence": 0.99,
            "reason": f"spy_top_intent:{self.sentinel_id}",
        }
        return self._wrap(payload, timeout_ms, kwargs)

    def _semantic_response(self, prompt: str, timeout_ms: int, kwargs: dict[str, Any]) -> dict[str, Any]:
        text = self._extract_user_text(prompt)
        payload = self._scenario_payload(text)
        payload["ranking_signals"] = {
            **dict(payload.get("ranking_signals") or {}),
            "spy_marker": self.sentinel_id,
        }
        payload["soft_preferences"] = {
            **dict(payload.get("soft_preferences") or {}),
            "spy_marker": self.sentinel_id,
        }
        return self._wrap(payload, timeout_ms, kwargs)

    def _scenario_payload(self, text: str) -> dict[str, Any]:
        for marker, payload in self._scenario_payloads.items():
            if marker == "__default__":
                return dict(payload)
            if marker and marker in text:
                return dict(payload)

        if "第一家" in text and "券" in text:
            return {
                "top_intent": "local_life",
                "task_type": "coupon_query",
                "primary_task": "coupon_query",
                "facets": [{"name": "coupon", "required": True}],
                "merchant_mentions": [],
                "reference_mentions": ["第一家"],
                "comparison_targets": [],
                "ordinal_references": ["第一家"],
                "deictic_references": [],
                "focused_facets": ["coupon"],
                "comparison_focus": "",
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {"query_terms": ["火锅"]},
                "follow_up": {"is_follow_up": True, "refine_action": "coupon_lookup"},
                "confidence": 0.98,
                "need_context": False,
            }

        if "这家" in text and ("比" in text or "哪个好" in text):
            return {
                "top_intent": "local_life",
                "task_type": "comparison",
                "primary_task": "comparison",
                "facets": [],
                "merchant_mentions": ["海底捞"],
                "reference_mentions": ["这家"],
                "comparison_targets": [
                    {"shop_name": "这家", "reference": "deictic", "source_text": "这家"},
                    {"shop_name": "海底捞", "reference": "explicit", "source_text": "海底捞"},
                ],
                "ordinal_references": [],
                "deictic_references": ["这家"],
                "focused_facets": [],
                "comparison_focus": "overall",
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {"query_terms": ["海底捞"]},
                "follow_up": {"is_follow_up": True, "refine_action": "comparison"},
                "confidence": 0.97,
                "need_context": True,
            }

        if "便宜一点" in text:
            return {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation_refine",
                "facets": [],
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "focused_facets": ["price"],
                "comparison_focus": "",
                "hard_constraints": {},
                "soft_preferences": {"price_preference": "cheap"},
                "ranking_signals": {"query_terms": ["火锅"], "price_preference": "cheap"},
                "follow_up": {"is_follow_up": True, "refine_action": "cheaper"},
                "confidence": 0.97,
                "need_context": True,
            }

        if ("海底捞" in text and "山城一锅" in text) or ("海底捞" in text and "哪个好" in text):
            return {
                "top_intent": "local_life",
                "task_type": "comparison",
                "primary_task": "comparison",
                "facets": [],
                "merchant_mentions": ["海底捞", "山城一锅"],
                "reference_mentions": [],
                "comparison_targets": [
                    {"shop_name": "海底捞", "reference": "explicit", "source_text": "海底捞"},
                    {"shop_name": "山城一锅", "reference": "explicit", "source_text": "山城一锅"},
                ],
                "ordinal_references": [],
                "deictic_references": [],
                "focused_facets": [],
                "comparison_focus": "overall",
                "hard_constraints": {},
                "soft_preferences": {},
                "ranking_signals": {"query_terms": ["海底捞", "山城一锅"]},
                "follow_up": None,
                "confidence": 0.98,
                "need_context": False,
            }

        if "约会" in text or "现在营业" in text or "有券" in text:
            return {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "primary_task": "recommendation",
                "facets": [
                    {"name": "open_status", "required": True},
                    {"name": "coupon", "required": False},
                    {"name": "distance", "required": False},
                ],
                "merchant_mentions": [],
                "reference_mentions": [],
                "comparison_targets": [],
                "ordinal_references": [],
                "deictic_references": [],
                "focused_facets": [],
                "comparison_focus": "",
                "hard_constraints": {"category": "火锅"},
                "soft_preferences": {"scene": "date"},
                "ranking_signals": {"query_terms": ["火锅"], "scene_terms": ["约会"]},
                "follow_up": None,
                "confidence": 0.98,
                "need_context": False,
            }

        return {
            "top_intent": "local_life",
            "task_type": "recommendation",
            "primary_task": "recommendation",
            "facets": [],
            "merchant_mentions": [],
            "reference_mentions": [],
            "comparison_targets": [],
            "ordinal_references": [],
            "deictic_references": [],
            "focused_facets": [],
            "comparison_focus": "",
            "hard_constraints": {},
            "soft_preferences": {},
            "ranking_signals": {"query_terms": ["火锅"]},
            "follow_up": None,
            "confidence": 0.95,
            "need_context": False,
        }

    def _verbalizer_response(self, prompt: str, timeout_ms: int, kwargs: dict[str, Any]) -> dict[str, Any]:
        answer_type = self._extract_scalar(prompt, "- 意图类型:")
        selected = self._extract_json_list(prompt, "- 选择的目标店面:")
        ranking = self._extract_json_list(prompt, "- 综合排序:")
        uncertainties = self._extract_json_list(prompt, "- 不确定项/无法确认项:")
        main_recommendation = self._extract_json_object(prompt, "- 主推荐店:")

        shop_names = [str(item.get("shop_name", "")).strip() for item in ranking or selected if str(item.get("shop_name", "")).strip()]
        if answer_type == "comparison" and len(shop_names) >= 2:
            text = f"综合当前已知信息，我会优先推荐{shop_names[0]}，其次是{shop_names[1]}。"
        elif answer_type == "recommendation" and shop_names:
            preview = "、".join(shop_names[:3])
            text = f"附近这几家更值得优先看：{preview}。"
        elif answer_type == "single_shop":
            target_name = ""
            if selected:
                target_name = str(selected[0].get("shop_name", "")).strip()
            if not target_name and main_recommendation:
                target_name = str(main_recommendation.get("shop_name", "")).strip()
            target_name = target_name or "这家店"
            if uncertainties:
                text = f"{target_name}这项信息我先按当前已知结果回答，暂时无法确认未查到的部分。"
            else:
                text = f"{target_name}这项信息我已经按当前查询结果整理好了。"
        else:
            target_name = str(main_recommendation.get("shop_name", "")).strip() if main_recommendation else ""
            text = f"我会优先参考{target_name or '当前结果'}来回答。"

        payload = {"natural_response": text}
        return self._wrap(payload, timeout_ms, kwargs)

    def _extract_scalar(self, prompt: str, label: str) -> str:
        for line in prompt.splitlines():
            if line.startswith(label):
                return line.split(":", 1)[1].strip()
        return ""

    def _extract_json_list(self, prompt: str, label: str) -> list[dict[str, Any]] | list[str]:
        raw = self._extract_json_fragment(prompt, label)
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    def _extract_json_object(self, prompt: str, label: str) -> dict[str, Any]:
        raw = self._extract_json_fragment(prompt, label)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _extract_json_fragment(self, prompt: str, label: str) -> str:
        pattern = re.escape(label) + r"\s*(.+)"
        match = re.search(pattern, prompt)
        return match.group(1).strip() if match else ""

    def _wrap(self, payload: dict[str, Any], timeout_ms: int, kwargs: dict[str, Any]) -> dict[str, Any]:
        raw_payload = json.dumps(
            {
                **payload,
                "_sentinel": self.sentinel_id,
                "_spy_backend": self.llm_backend,
            },
            ensure_ascii=False,
        )
        return {
            "ok": True,
            "content": payload,
            "confidence": float(payload.get("confidence", 0.95)),
            "raw": raw_payload,
            "error_code": "",
            "error_message": "",
            "llm_backend": self.llm_backend,
            "attempts": 1,
            "temperature": kwargs.get("temperature", 0.0),
            "timeout_ms": timeout_ms,
        }


@pytest.fixture
def spy_backend() -> SpyRealLLMBackend:
    """Create a fresh SpyRealLLMBackend for each test."""
    return SpyRealLLMBackend()


@pytest.fixture
def poison_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Crash tests when a forbidden fallback path is touched."""

    def _poison(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("FALLBACK_ACTIVATED")

    monkeypatch.setattr("local_life_agent.semantic.intent_parser._fallback_semantic_frame", _poison)
    monkeypatch.setattr("local_life_agent.semantic.intent_parser._fallback_intent", _poison)
    monkeypatch.setattr("local_life_agent.semantic.slot_extractor.extract_slots", _poison)
    monkeypatch.setattr("local_life_agent.llm.client._default_llm_backend", _poison)
