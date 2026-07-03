from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from local_life_agent.answer.verifier import verify_answer as _real_verify_answer
from local_life_agent.input.normalizer import normalize_text
from local_life_agent.llm.client import clear_llm_backend, set_llm_backend
from local_life_agent.observability.trace import sanitize_payload
from local_life_agent.tests.conftest import SpyRealLLMBackend
from local_life_agent.tests.fakes import mock_tools


def _shop_summary(shop_id: str, shop_name: str) -> dict[str, Any]:
    return {
        "shop_id": shop_id,
        "shop_name": shop_name,
        "category": "火锅",
        "rating": 4.5,
        "avg_price": 88.0,
        "open_status": "open",
        "tags": ["约会", "聚餐"],
        "aliases": [shop_name],
    }


def _build_alias_index_from_mock_data() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for shop in mock_tools._all_shops():
        canonical = normalize_text(str(shop.get("shop_name", "") or "")).strip()
        if not canonical:
            continue
        aliases = {canonical}
        alias_field = normalize_text(str(shop.get("alias", "") or "")).strip()
        if alias_field:
            aliases.add(alias_field)
        for alias_item in shop.get("aliases", []) or []:
            alias_norm = normalize_text(str(alias_item)).strip()
            if alias_norm:
                aliases.add(alias_norm)
        index[canonical] = sorted(aliases)
    return index


@dataclass
class FakeLocalLifeBackend:
    """Deterministic test backend for P6 matrix scenarios."""

    scenario_name: str = ""
    empty_search_queries: set[str] = field(default_factory=set)
    tool_failures: dict[str, str] = field(default_factory=dict)
    verify_should_fail: bool = False
    verify_failure_phrase: str = "unsupported claim"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    last_final_state: dict[str, Any] = field(default_factory=dict)
    captured_graph: Any | None = None

    def __post_init__(self) -> None:
        self._llm = FakeComplexQueryLLMBackend(scenario_name=self.scenario_name)

    @property
    def llm_backend(self) -> str:
        return self._llm.llm_backend

    @property
    def backend_kind(self) -> str:
        return self._llm.llm_backend

    def __call__(self, prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs: Any) -> dict[str, Any]:
        self.llm_calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "timeout_ms": timeout_ms,
                "kwargs": dict(kwargs),
            }
        )
        return self._llm(prompt, system_prompt=system_prompt, temperature=temperature, timeout_ms=timeout_ms, **kwargs)

    def llm_backend_call(self, prompt: str, system_prompt: str = "", temperature: float = 0.0, timeout_ms: int = 3000, **kwargs: Any) -> dict[str, Any]:
        return self(prompt, system_prompt=system_prompt, temperature=temperature, timeout_ms=timeout_ms, **kwargs)

    def dispatch_tool_call(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(tool_name)
        args = dict(args or {})
        self.tool_calls.append({"tool_name": tool_name, "args": args})

        if tool_name == "resolve_shop":
            return self.resolve_shop(
                str(args.get("query", "")),
                location=args.get("location"),
                session_shop_ids=args.get("session_shop_ids"),
            )

        failure_mode = self.tool_failures.get(tool_name, "")
        if failure_mode == "timeout":
            raise TimeoutError(f"{tool_name} timed out (fake backend)")
        if failure_mode == "failed":
            return self._failed_result(tool_name, args, error_code="NETWORK_ERROR", error_message=f"{tool_name} failed")
        if failure_mode == "unknown":
            return self._unknown_result(tool_name, args)
        if failure_mode == "empty":
            return self._empty_result(tool_name, args)

        if tool_name == "search_shops":
            return self.search_shops(str(args.get("query", "")), location=args.get("location"), limit=args.get("limit"))
        if tool_name == "get_shop_detail":
            return self.get_shop_detail(str(args.get("shop_id", "")))
        if tool_name == "get_coupon_list":
            return self.get_coupon_list(str(args.get("shop_id", "")))
        if tool_name == "check_open_status":
            return self.check_open_status(str(args.get("shop_id", "")))
        if tool_name == "get_distance_eta":
            return self.get_distance_eta(str(args.get("shop_id", "")), args.get("from_location") or {"lat": 39.9609, "lng": 116.3581})
        if tool_name == "get_deal_list":
            return self.get_deal_list(str(args.get("shop_id", "")))
        if tool_name == "get_shop_review_summary":
            shop_ids = args.get("shop_ids") or [str(args.get("shop_id", ""))]
            return self.get_shop_review_summary([str(item) for item in shop_ids if str(item).strip()])
        if tool_name == "get_shop_cards":
            return self.get_shop_cards([str(item) for item in args.get("shop_ids", []) or []])
        raise AssertionError(f"Unexpected tool for fake backend: {tool_name}")

    def resolve_shop(
        self,
        query: str,
        *,
        location: dict[str, float] | None = None,
        session_shop_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        compact = str(query or "").strip()
        if not compact:
            return {"status": "NOT_FOUND", "shop": None, "candidates": [], "confidence": 0.0, "error_code": "SHOP_NOT_FOUND"}
        if "海底捞人民广场店" in compact:
            return {
                "status": "RESOLVED",
                "shop": _shop_summary("shop_007", "海底捞(牡丹园店)"),
                "confidence": 0.96,
                "error_code": None,
            }
        if "海底捞" in compact or "川味轩" in compact or "木屋烧烤" in compact:
            return mock_tools.resolve_shop(compact, location=location, session_shop_ids=session_shop_ids)
        if session_shop_ids:
            return mock_tools.resolve_shop(compact, location=location, session_shop_ids=session_shop_ids)
        return {"status": "NOT_FOUND", "shop": None, "candidates": [], "confidence": 0.0, "error_code": "SHOP_NOT_FOUND"}

    def search_shops(self, query: str, location: dict[str, float] | None = None, limit: int | None = None) -> dict[str, Any]:
        compact = str(query or "").strip()
        if compact in self.empty_search_queries or any(token in compact for token in self.empty_search_queries):
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        if "日料" in compact and ("50" in compact or "50以内" in compact):
            return {"success": True, "result_status": "empty", "data": [], "total": 0}
        return mock_tools.search_shops(compact, location=location, limit=limit)

    def get_shop_detail(self, shop_id: str) -> dict[str, Any]:
        if shop_id == "shop_007":
            return mock_tools.get_shop_detail(shop_id)
        return mock_tools.get_shop_detail(shop_id)

    def get_coupon_list(self, shop_id: str) -> dict[str, Any]:
        return mock_tools.get_coupon_list(shop_id)

    def check_open_status(self, shop_id: str) -> dict[str, Any]:
        return mock_tools.check_open_status(shop_id)

    def get_distance_eta(self, shop_id: str, from_location: dict[str, float]) -> dict[str, Any]:
        return mock_tools.get_distance_eta(shop_id, from_location)

    def get_shop_cards(self, shop_ids: list[str]) -> dict[str, Any]:
        return mock_tools.get_shop_cards(shop_ids, user_location={"lat": 39.9609, "lng": 116.3581})

    def get_shop_review_summary(self, shop_ids: list[str]) -> dict[str, Any]:
        return mock_tools.get_shop_review_summary(shop_ids)

    def get_deal_list(self, shop_id: str) -> dict[str, Any]:
        return mock_tools.get_deal_list(shop_id)

    def verify_answer(self, response_text: str, evidence: Any, task_type: str) -> dict[str, Any]:
        if self.verify_should_fail and self.verify_failure_phrase in response_text:
            return {
                "passed": False,
                "violation": "unsupported_claim",
                "failure_code": "unsupported_claim",
                "issues": ["unsupported_claim"],
                "suggested_fix": "remove unsupported claim",
                "verifier_unknown_fields": [],
                "verifier_unsupported_claims": [response_text],
                "verifier_false_fields": [],
                "recoverable": True,
            }
        return _real_verify_answer(response_text, evidence, task_type)

    def _failed_result(self, tool_name: str, args: dict[str, Any], *, error_code: str, error_message: str) -> dict[str, Any]:
        shop_id = str(args.get("shop_id", "") or "")
        return {
            "success": False,
            "result_status": "failed",
            "data": None,
            "error_code": error_code,
            "error_message": error_message,
            "source": "fake_backend",
            "degraded": True,
            "tool_name": tool_name,
            "shop_id": shop_id,
        }

    def _unknown_result(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        shop_id = str(args.get("shop_id", "") or "")
        return {
            "success": False,
            "result_status": "unknown",
            "data": None,
            "error_code": "UNKNOWN",
            "error_message": f"{tool_name} unknown",
            "source": "fake_backend",
            "degraded": True,
            "tool_name": tool_name,
            "shop_id": shop_id,
        }

    def _empty_result(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        shop_id = str(args.get("shop_id", "") or "")
        return {
            "success": True,
            "result_status": "empty",
            "data": [],
            "total": 0,
            "source": "fake_backend",
            "degraded": False,
            "tool_name": tool_name,
            "shop_id": shop_id,
        }


class FakeComplexQueryLLMBackend(SpyRealLLMBackend):
    """Spy backend with richer facet coverage for the P6 matrix."""

    llm_backend = "fake_complex_query_llm"

    def _scenario_payload(self, text: str) -> dict[str, Any]:
        compact = str(text or "").replace(" ", "")
        payload = dict(super()._scenario_payload(text))

        def _facet(name: str, group: str, required: bool = False, value: Any | None = None) -> dict[str, Any]:
            item = {"name": name, "group": group, "required": required}
            if value is not None:
                item["value"] = value
            return item

        if "附近推荐几家适合约会" in compact and "人均100左右" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        _facet("nearby", "location", True),
                        _facet("restaurant", "category", True),
                        _facet("date_scene", "scene", True),
                        _facet("open_now", "status", False),
                        _facet("coupon", "deal", False),
                        _facet("budget_around_x", "price", False, 100),
                    ],
                    "merchant_mentions": [],
                    "reference_mentions": [],
                    "comparison_targets": [],
                    "ordinal_references": [],
                    "deictic_references": [],
                    "focused_facets": ["nearby", "restaurant", "date_scene", "open_now", "coupon", "budget_around_x"],
                    "comparison_focus": "",
                    "hard_constraints": {"category": "餐厅"},
                    "soft_preferences": {"scene": "date", "budget_around_x": 100},
                    "ranking_signals": {"query_terms": ["餐厅"], "scene_terms": ["约会"], "budget_around_x": 100},
                    "follow_up": None,
                    "confidence": 0.98,
                    "need_context": False,
                }
            )
            return payload

        if "第一家和第二家" in compact and ("带娃" in compact or "更便宜" in compact):
            payload.update(
                {
                    "task_type": "comparison",
                    "primary_task": "comparison",
                    "facets": [
                        _facet("ordinal_reference", "reference", True),
                        _facet("comparison_targets", "reference", True),
                        _facet("kid_friendly", "preference", False),
                        _facet("price_compare", "price", False),
                    ],
                    "merchant_mentions": [],
                    "reference_mentions": ["第一家", "第二家"],
                    "comparison_targets": [
                        {"shop_name": "第一家", "reference": "ordinal", "source_text": "第一家"},
                        {"shop_name": "第二家", "reference": "ordinal", "source_text": "第二家"},
                    ],
                    "ordinal_references": ["第一家", "第二家"],
                    "deictic_references": [],
                    "focused_facets": ["kid_friendly", "price_compare"],
                    "comparison_focus": "target_dimension",
                    "hard_constraints": {},
                    "soft_preferences": {"kid_friendly": True, "price_compare": True},
                    "ranking_signals": {"query_terms": ["带娃", "更便宜"]},
                    "follow_up": {"is_follow_up": True, "refine_action": "comparison"},
                    "confidence": 0.97,
                    "need_context": False,
                }
            )
            return payload

        if "这家有券吗" in compact and "现在开着吗" in compact and "离我多远" in compact:
            payload.update(
                {
                    "task_type": "single_shop_query",
                    "primary_task": "single_shop_fact",
                    "facets": [
                        _facet("current_shop", "reference", True),
                        _facet("coupon", "deal", True),
                        _facet("open_now", "status", True),
                        _facet("distance", "location", False),
                    ],
                    "merchant_mentions": [],
                    "reference_mentions": ["这家"],
                    "comparison_targets": [],
                    "ordinal_references": [],
                    "deictic_references": ["这家"],
                    "focused_facets": ["coupon", "open_now", "distance"],
                    "comparison_focus": "",
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "ranking_signals": {"query_terms": ["这家"], "requested_facets": ["coupon", "open_now", "distance"]},
                    "follow_up": None,
                    "confidence": 0.99,
                    "need_context": False,
                }
            )
            return payload

        if "这家有券吗" in compact or "这家店有券吗" in compact:
            payload.update(
                {
                    "task_type": "single_shop_query",
                    "primary_task": "coupon_query",
                    "facets": [
                        _facet("current_shop", "reference", True),
                        _facet("coupon", "deal", True),
                    ],
                    "merchant_mentions": [],
                    "reference_mentions": ["这家"],
                    "comparison_targets": [],
                    "ordinal_references": [],
                    "deictic_references": ["这家"],
                    "focused_facets": ["current_shop", "coupon"],
                    "comparison_focus": "",
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "ranking_signals": {"query_terms": ["这家"], "requested_facets": ["coupon"]},
                    "follow_up": {"is_follow_up": True, "refine_action": "resolve_current_shop"},
                    "confidence": 0.98,
                    "need_context": True,
                }
            )
            return payload

        if "海底捞人民广场店" in compact or "我说的是海底捞人民广场店" in compact:
            payload.update(
                {
                    "task_type": "single_shop_query",
                    "primary_task": "single_shop_query",
                    "facets": [
                        _facet("current_shop", "reference", True),
                        _facet("coupon", "deal", True),
                    ],
                    "merchant_mentions": ["海底捞人民广场店"],
                    "reference_mentions": ["这家"],
                    "comparison_targets": [],
                    "ordinal_references": [],
                    "deictic_references": ["这家"],
                    "focused_facets": ["coupon", "current_shop"],
                    "comparison_focus": "",
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "ranking_signals": {"query_terms": ["海底捞人民广场店"], "requested_facets": ["coupon"]},
                    "follow_up": {"is_follow_up": True, "refine_action": "resolve_current_shop"},
                    "confidence": 0.99,
                    "need_context": False,
                }
            )
            return payload

        if "第一家有券吗" in compact:
            payload.update(
                {
                    "task_type": "single_shop_query",
                    "primary_task": "coupon_query",
                    "facets": [_facet("ordinal_reference", "reference", True), _facet("coupon", "deal", True)],
                    "merchant_mentions": [],
                    "reference_mentions": ["第一家"],
                    "comparison_targets": [],
                    "ordinal_references": ["第一家"],
                    "deictic_references": [],
                    "focused_facets": ["coupon", "ordinal_reference"],
                    "comparison_focus": "",
                    "hard_constraints": {},
                    "soft_preferences": {},
                    "ranking_signals": {"requested_facets": ["coupon"], "reference": "ordinal"},
                    "follow_up": {"is_follow_up": True, "refine_action": "coupon_lookup"},
                    "confidence": 0.98,
                    "need_context": True,
                }
            )
            return payload

        if "推荐附近火锅" in compact and "第一家远吗" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        _facet("nearby", "location", True),
                        _facet("hotpot", "category", True),
                        _facet("ordinal_reference", "reference", True),
                        _facet("distance", "location", False),
                    ],
                    "merchant_mentions": [],
                    "reference_mentions": ["第一家"],
                    "comparison_targets": [],
                    "ordinal_references": ["第一家"],
                    "deictic_references": [],
                    "focused_facets": ["nearby", "hotpot", "ordinal_reference", "distance"],
                    "comparison_focus": "",
                    "hard_constraints": {"category": "火锅"},
                    "soft_preferences": {"nearby_preferred": True},
                    "ranking_signals": {"query_terms": ["火锅"], "nearby_preferred": True},
                    "follow_up": None,
                    "confidence": 0.97,
                    "need_context": True,
                }
            )
            return payload

        if "高评分日料" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        _facet("nearby", "location", True),
                        _facet("restaurant", "category", True),
                        _facet("date_scene", "scene", False),
                        _facet("open_now", "status", False),
                        _facet("coupon", "deal", False),
                        _facet("budget", "price", False),
                    ],
                    "hard_constraints": {"category": "日料"},
                    "soft_preferences": {"rating": "high"},
                    "ranking_signals": {"query_terms": ["日料"], "rating_preferred": True},
                    "confidence": 0.94,
                    "need_context": False,
                }
            )
            return payload

        if "安静适合聊天的咖啡店" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        _facet("coffee", "category", True),
                        _facet("quiet", "scene", True),
                    ],
                    "hard_constraints": {"category": "咖啡"},
                    "soft_preferences": {"scene": "quiet"},
                    "ranking_signals": {"query_terms": ["咖啡店"], "scene_terms": ["安静"]},
                    "confidence": 0.95,
                    "need_context": False,
                }
            )
            return payload

        if "热闹一点" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation_refine",
                    "facets": [
                        _facet("coffee", "category", True),
                        _facet("lively", "scene", True),
                    ],
                    "hard_constraints": {"category": "咖啡"},
                    "soft_preferences": {"scene": "lively"},
                    "ranking_signals": {"query_terms": ["咖啡店"], "scene_terms": ["热闹"]},
                    "conflicting_facets": [
                        {"facets": ["quiet", "lively"], "reason": "scene_conflict", "severity": "high"}
                    ],
                    "ranking_policy": {
                        "primary_facets": ["lively"],
                        "secondary_facets": ["coffee"],
                        "tradeoff_notes": ["与上轮 quiet 偏好冲突"],
                    },
                    "follow_up": {"is_follow_up": True, "refine_action": "lively"},
                    "confidence": 0.93,
                    "need_context": False,
                }
            )
            return payload

        if "所有工具超时" in compact or "所有工具失败" in compact:
            payload.update(
                {
                    "task_type": "recommendation",
                    "primary_task": "recommendation",
                    "facets": [
                        _facet("nearby", "location", True),
                        _facet("restaurant", "category", True),
                        _facet("open_now", "status", False),
                        _facet("coupon", "deal", False),
                        _facet("distance", "location", False),
                    ],
                    "hard_constraints": {"category": "火锅"},
                    "soft_preferences": {"open_now_preferred": True},
                    "ranking_signals": {"query_terms": ["火锅"]},
                    "confidence": 0.9,
                    "need_context": False,
                }
            )
            return payload

        if "格式异常" in compact or "LLM返回格式异常" in compact:
            return {
                "top_intent": "local_life",
                "task_type": "unknown",
                "primary_task": "unknown",
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
                "ranking_signals": {},
                "follow_up": None,
                "confidence": 0.12,
                "need_context": True,
            }

        return payload


def install_fake_runtime(
    monkeypatch: Any,
    backend: FakeLocalLifeBackend,
    *,
    patch_answer_verifier: bool = True,
) -> FakeLocalLifeBackend:
    """Install a fully deterministic test runtime around the graph."""

    from local_life_agent import agent
    from local_life_agent.engine import graph_builder
    from local_life_agent.engine.subgraphs import response_subgraph
    from local_life_agent.semantic import alias_index
    from local_life_agent.semantic import slot_extractor
    from local_life_agent.tools import db_client, db_tools

    real_build_graph = graph_builder.build_graph

    set_llm_backend(backend)
    monkeypatch.setattr(graph_builder, "dispatch_tool_call", backend.dispatch_tool_call)
    monkeypatch.setattr(graph_builder, "resolve_shop", backend.resolve_shop)
    monkeypatch.setattr(alias_index, "build_alias_index", _build_alias_index_from_mock_data)
    monkeypatch.setattr(alias_index, "iter_alias_tokens", lambda: [(alias, canonical) for canonical, aliases in _build_alias_index_from_mock_data().items() for alias in aliases])
    monkeypatch.setattr(slot_extractor, "iter_alias_tokens", lambda: [(alias, canonical) for canonical, aliases in _build_alias_index_from_mock_data().items() for alias in aliases])
    monkeypatch.setattr(db_tools, "build_alias_index", _build_alias_index_from_mock_data)
    monkeypatch.setattr(db_client, "query_all_shops", lambda: [dict(shop) for shop in mock_tools._all_shops()])
    monkeypatch.setattr(db_client, "query_shops_by_keyword", lambda query, limit=None: list(mock_tools.search_shops(query, limit=limit).get("data", [])))
    monkeypatch.setattr(db_client, "query_shop_by_id", lambda shop_id: mock_tools.get_shop_detail(shop_id).get("data"))
    monkeypatch.setattr(db_client, "query_coupons_by_shop_id", lambda shop_id: list(mock_tools.get_coupon_list(shop_id).get("data", [])))

    def _build_graph_capture() -> Any:
        compiled = real_build_graph()

        class _CaptureGraph:
            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def invoke(self, initial: dict[str, Any], config: dict[str, Any] | None = None) -> Any:
                result = self._inner.invoke(initial, config=config)
                backend.last_final_state = dict(result) if isinstance(result, dict) else {}
                return result

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        backend.captured_graph = _CaptureGraph(compiled)
        return backend.captured_graph

    monkeypatch.setattr(graph_builder, "build_graph", _build_graph_capture)
    monkeypatch.setattr(graph_builder, "_GRAPH_CACHE", None, raising=False)
    monkeypatch.setattr(agent, "_GRAPH_CACHE", None, raising=False)
    if patch_answer_verifier:
        monkeypatch.setattr(response_subgraph, "verify_answer", backend.verify_answer)
    return backend


def clear_fake_runtime() -> None:
    clear_llm_backend()
