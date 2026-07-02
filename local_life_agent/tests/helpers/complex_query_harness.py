from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_life_agent.agent import run_agent_graph
from local_life_agent.domain.state import SessionState
from local_life_agent.session.store import get_session_store

from .fake_backends import FakeLocalLifeBackend, install_fake_runtime


_GOLDEN_TRACE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "golden_traces"


def load_golden_trace(name: str) -> dict[str, Any]:
    return json.loads((_GOLDEN_TRACE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _normalize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return _normalize(value.model_dump())
        except Exception:
            return {}
    if hasattr(value, "__dict__") and not isinstance(value, type):
        try:
            return _normalize({k: v for k, v in vars(value).items() if not str(k).startswith("_")})
        except Exception:
            return {}
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def build_backend(case: dict[str, Any]) -> FakeLocalLifeBackend:
    backend = FakeLocalLifeBackend(
        scenario_name=str(case.get("name", "") or ""),
        empty_search_queries=set(case.get("empty_search_queries") or []),
        tool_failures=dict(case.get("tool_failures") or {}),
        verify_should_fail=bool(case.get("verify_should_fail", False)),
        verify_failure_phrase=str(case.get("verify_failure_phrase", "unsupported claim") or "unsupported claim"),
    )
    return backend


def seed_session_state(session_id: str, initial_session_state: dict[str, Any] | None) -> None:
    if not initial_session_state:
        return
    session_store = get_session_store()
    session_store.save(session_id, SessionState.model_validate(initial_session_state))


def run_case(
    case: dict[str, Any],
    monkeypatch: Any,
    *,
    backend: FakeLocalLifeBackend | None = None,
) -> tuple[list[Any], FakeLocalLifeBackend]:
    records, backend = run_case_turns(case, monkeypatch, backend=backend)
    return [response for response, _state in records], backend


def run_case_turns(
    case: dict[str, Any],
    monkeypatch: Any,
    *,
    backend: FakeLocalLifeBackend | None = None,
) -> tuple[list[tuple[Any, dict[str, Any]]], FakeLocalLifeBackend]:
    backend = backend or build_backend(case)
    install_fake_runtime(monkeypatch, backend)
    session_id = str(case.get("session_id", "") or f"p6_{case.get('name', 'case')}")
    seed_session_state(session_id, case.get("initial_session_state"))

    records: list[tuple[Any, dict[str, Any]]] = []
    turns = list(case.get("turns") or [case.get("query")])
    for turn in turns:
        if not isinstance(turn, str):
            continue
        response = run_agent_graph(turn, session_id)
        records.append((response, final_state_snapshot(backend)))
    return records, backend


def response_debug(response: Any) -> dict[str, Any]:
    debug = getattr(response, "debug", None)
    if debug is None:
        return {}
    return {
        "answer_text": getattr(response, "answer_text", ""),
        "trace_id": getattr(response, "trace_id", ""),
        "session_id": getattr(response, "session_id", ""),
        "semantic_frame": getattr(debug, "semantic_frame", {}),
        "execution_plan": getattr(debug, "execution_plan", {}),
        "tool_results": getattr(debug, "tool_results", {}),
        "evidence_pack": getattr(debug, "evidence_pack", {}),
        "session_state_before": getattr(debug, "session_state_before", {}),
        "session_state_after": getattr(debug, "session_state_after", {}),
        "state_update_plan": getattr(debug, "state_update_plan", {}),
        "answer_source": getattr(debug, "answer_source", ""),
        "answer_verify_passed": getattr(debug, "answer_verify_passed", True),
        "answer_verify_violations": getattr(debug, "answer_verify_violations", []),
        "rewrite_needed": getattr(debug, "rewrite_needed", False),
        "rewrite_count": getattr(debug, "rewrite_count", 0),
        "rewrite_reason": getattr(debug, "rewrite_reason", ""),
        "fallback_reason": getattr(debug, "fallback_reason", ""),
        "final_safety_status": getattr(debug, "final_safety_status", "safe"),
    }


def final_state_snapshot(backend: FakeLocalLifeBackend) -> dict[str, Any]:
    return _normalize(dict(backend.last_final_state or {}))


def final_state_field(backend: FakeLocalLifeBackend, field_name: str, default: Any = None) -> Any:
    return final_state_snapshot(backend).get(field_name, default)
