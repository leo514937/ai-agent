from __future__ import annotations

import json
import importlib

import pytest

from local_life_agent.agent import AgentResponse, DebugInfo
from local_life_agent.eval.run_eval import load_cases, run_eval, run_eval_file, run_eval_profile


def _fake_response(
    *,
    trace_id: str,
    session_id: str,
    task_type: str = "recommendation",
    selected_flow: str = "recommendation_flow",
    answer_source: str = "llm_verbalizer",
    candidate_count: int = 2,
    reference_resolution_source: str = "semantic_frame",
    answer_verify_passed: bool = True,
    answer_verify_violations: list[str] | None = None,
    rewrite_count: int = 0,
) -> AgentResponse:
    return AgentResponse(
        answer_text="测试回答",
        trace_id=trace_id,
        session_id=session_id,
        debug=DebugInfo(
            execution_trace=[],
            turn_trace={
                "trace_id": trace_id,
                "session_id": session_id,
                "turn_id": "turn_1",
                "user_text": "测试",
                "top_intent": "local_life",
                "semantic_source": "spy_real_llm",
                "llm_backend": "spy_real_llm",
                "llm_backend_kind": "spy_real_llm",
                "llm_backend_family": "spy_real_llm",
                "llm_called": True,
                "task_type": task_type,
                "primary_task": task_type,
                "selected_flow": selected_flow,
                "target_status": "RESOLVED",
                "reference_resolution_source": reference_resolution_source,
                "candidate_count": candidate_count,
                "decision_type": "comparison" if task_type == "comparison" else "recommendation",
                "tool_call_count": 2,
                "answer_source": answer_source,
                "answer_verify_passed": answer_verify_passed,
                "answer_verify_violations": answer_verify_violations or [],
                "rewrite_count": rewrite_count,
                "fallback_reason": "" if answer_verify_passed else "b2_mini_verifier:ranking_changed",
                "final_safety_status": "safe" if answer_verify_passed else "fallback",
                "events": [],
            },
            semantic_frame={"top_intent": "local_life", "task_type": task_type, "primary_task": task_type},
            answer_source=answer_source,
            answer_verify_passed=answer_verify_passed,
            answer_verify_violations=answer_verify_violations or [],
            rewrite_count=rewrite_count,
            final_safety_status="safe" if answer_verify_passed else "fallback",
        ),
    )


def test_load_cases_reads_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"case_id": "c1", "turns": [{"user": "附近推荐火锅"}]}, ensure_ascii=False) + "\n", encoding="utf-8")
    cases = load_cases(path)
    assert cases[0]["case_id"] == "c1"


def test_run_eval_handles_single_turn(monkeypatch, tmp_path):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    monkeypatch.setattr(run_eval_module, "run_agent_graph", lambda text, session_id="": _fake_response(trace_id="trace_1", session_id=session_id))
    report = run_eval(
        [
            {
                "case_id": "c1",
                "category": "core",
                "turns": [{"user": "附近推荐火锅"}],
                "expected": {"top_intent": "local_life", "task_type": "recommendation", "selected_flow": "recommendation_flow"},
            }
        ],
        backend="rule_based",
        output_dir=tmp_path,
        write_reports=True,
    )
    assert report["summary"]["passed"] == 1
    assert report["cases"][0]["status"] == "passed"
    assert report["report_paths"]["json"]


def test_run_eval_handles_multi_turn_assertions(monkeypatch):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    calls = {"count": 0}

    def fake_run_agent(text, session_id=""):
        calls["count"] += 1
        if calls["count"] == 1:
            return _fake_response(trace_id="trace_1", session_id=session_id, reference_resolution_source="raw_text_fallback")
        return _fake_response(trace_id="trace_2", session_id=session_id, task_type="comparison", selected_flow="comparison_flow")

    monkeypatch.setattr(run_eval_module, "run_agent_graph", fake_run_agent)
    report = run_eval(
        [
            {
                "case_id": "c2",
                "category": "context",
                "turns": [{"user": "川味轩怎么样？"}, {"user": "这家和海底捞比呢？"}],
                "expected": {
                    "task_type": "comparison",
                    "selected_flow": "comparison_flow",
                    "turn_assertions": [{}, {"task_type": "comparison"}],
                },
            }
        ],
        backend="rule_based",
        write_reports=False,
    )
    assert report["summary"]["passed"] == 1


def test_run_eval_writes_json_and_markdown(monkeypatch, tmp_path):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    monkeypatch.setattr(run_eval_module, "run_agent_graph", lambda text, session_id="": _fake_response(trace_id="trace_report", session_id=session_id))
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"case_id": "c3", "category": "core", "turns": [{"user": "附近推荐火锅"}], "expected": {"top_intent": "local_life"}}, ensure_ascii=False) + "\n", encoding="utf-8")
    report = run_eval_file(path, backend="rule_based", output_dir=tmp_path, write_reports=True)
    assert (tmp_path / "latest_eval_report.json").exists()
    assert (tmp_path / "latest_eval_report.md").exists()
    assert report["summary"]["passed"] == 1


def test_real_llm_missing_key_is_skipped(monkeypatch):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    monkeypatch.setattr(run_eval_module.config, "load_llm_api_key", lambda: "")
    report = run_eval(
        [
            {
                "case_id": "c4",
                "category": "real_llm_optional",
                "turns": [{"user": "附近推荐火锅"}],
                "expected": {"allow_skipped_if_no_api_key": True},
            }
        ],
        backend="real_llm",
        write_reports=False,
    )
    assert report["summary"]["skipped"] == 1
    assert report["cases"][0]["status"] == "skipped"


def test_run_eval_profile_loads_relative_case_path(monkeypatch, tmp_path):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    monkeypatch.setattr(run_eval_module, "run_agent_graph", lambda text, session_id="": _fake_response(trace_id="trace_profile", session_id=session_id))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {"case_id": "p1", "category": "real_e2e_acceptance", "turns": [{"user": "附近推荐火锅"}], "expected": {"top_intent": "local_life"}},
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    profile_path = tmp_path / "real_e2e.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "name: real_e2e",
                "mode: acceptance",
                "backend: real_llm",
                "tool_backend: db",
                "cases: cases.jsonl",
            ]
        ),
        encoding="utf-8",
    )
    report = run_eval_profile(profile_path, output_dir=tmp_path, write_reports=False)
    assert report["summary"]["passed"] == 1
    assert report["profile"]["cases"] == str(cases_path.resolve())


def test_run_eval_profile_real_e2e_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    profile_path = tmp_path / "real_e2e.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "name: real_e2e",
                "mode: acceptance",
                "backend: real_llm",
                "tool_backend: db",
                "cases: cases.jsonl",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="API key"):
        run_eval_profile(profile_path, output_dir=tmp_path, write_reports=False)


def test_run_eval_acceptance_assertions_fail_on_forbidden_paths(monkeypatch):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")

    def fake_run_agent(text, session_id=""):
        return AgentResponse(
            answer_text="模板回答",
            trace_id="trace_bad",
            session_id=session_id,
            debug=DebugInfo(
                execution_trace=[],
                turn_trace={
                    "trace_id": "trace_bad",
                    "session_id": session_id,
                    "turn_id": "turn_1",
                    "user_text": text,
                    "top_intent": "local_life",
                    "semantic_source": "fallback_rules",
                    "llm_backend": "spy_real_llm",
                    "llm_backend_kind": "spy_real_llm",
                    "llm_backend_family": "spy_real_llm",
                    "tool_backend": "mock",
                    "llm_called": True,
                    "task_type": "single_shop_query",
                    "primary_task": "single_shop_query",
                    "selected_flow": "single_shop_query_flow",
                    "target_status": "RESOLVED",
                    "reference_resolution_source": "semantic_frame",
                    "candidate_count": 1,
                    "decision_type": "single_shop",
                    "tool_call_count": 1,
                    "answer_source": "template_fallback",
                    "answer_verify_passed": True,
                    "answer_verify_violations": [],
                    "rewrite_count": 0,
                    "fallback_reason": "semantic fallback",
                    "fallback_used": True,
                    "legacy_used": True,
                    "evidence_incomplete": True,
                    "final_safety_status": "safe",
                    "events": [],
                },
                semantic_frame={
                    "top_intent": "local_life",
                    "task_type": "single_shop_query",
                    "semantic_source": "fallback_rules",
                    "llm_backend": "spy_real_llm",
                },
                answer_source="template_fallback",
                answer_verify_passed=True,
                final_safety_status="safe",
            ),
        )

    monkeypatch.setattr(run_eval_module, "run_agent_graph", fake_run_agent)
    report = run_eval(
        [
            {
                "case_id": "accept_bad_1",
                "category": "real_e2e_acceptance",
                "turns": [{"user": "海底捞有券吗"}],
                "expected": {
                    "expect_llm_backend_kind": "real_llm",
                    "forbid_semantic_sources": ["fallback_rules", "rule_based"],
                    "forbid_tool_backends": ["mock", "fake", "stub"],
                    "expect_answer_source": "llm_verbalizer",
                    "forbid_answer_sources": ["template", "template_fallback"],
                    "expect_legacy_used": False,
                    "expect_fallback_used": False,
                    "expect_evidence_incomplete": False,
                    "expect_terminal": "final_answer",
                    "forbid_fake_success": True,
                    "require_tool_results": True,
                },
            }
        ],
        backend="real_llm",
        write_reports=False,
    )
    assert report["summary"]["failed"] == 1
    failures = report["cases"][0]["failures"]
    assert any("expect_llm_backend_kind" in item for item in failures)
    assert any("forbid_semantic_sources" in item for item in failures)
    assert any("forbid_tool_backends" in item for item in failures)
    assert any("expect_answer_source" in item for item in failures)
    assert any("forbid_answer_sources" in item for item in failures)
    assert any("expect_legacy_used" in item for item in failures)
    assert any("expect_fallback_used" in item for item in failures)
    assert any("expect_evidence_incomplete" in item for item in failures)


def test_run_eval_acceptance_assertions_support_clarify_and_trusted_failure(monkeypatch):
    run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
    responses = [
        AgentResponse(
            answer_text="请告诉我是哪个海底捞门店，比如牡丹园店还是水晶城店。",
            trace_id="trace_clarify",
            session_id="sid1",
            clarification="请提供完整店名",
            debug=DebugInfo(
                execution_trace=[],
                turn_trace={
                    "trace_id": "trace_clarify",
                    "session_id": "sid1",
                    "turn_id": "turn_1",
                    "user_text": "海底捞有券吗",
                    "top_intent": "local_life",
                    "semantic_source": "real_llm",
                    "llm_backend": "real_llm",
                    "llm_backend_kind": "real_llm",
                    "llm_backend_family": "real_llm",
                    "tool_backend": "db",
                    "llm_called": True,
                    "task_type": "coupon_query",
                    "primary_task": "coupon_query",
                    "selected_flow": "single_shop_query_flow",
                    "target_status": "AMBIGUOUS",
                    "reference_resolution_source": "semantic_frame",
                    "candidate_count": 3,
                    "decision_type": "single_shop",
                    "tool_call_count": 1,
                    "answer_source": "llm_verbalizer",
                    "answer_verify_passed": True,
                    "answer_verify_violations": [],
                    "rewrite_count": 0,
                    "fallback_reason": "",
                    "fallback_used": False,
                    "legacy_used": False,
                    "evidence_incomplete": False,
                    "final_safety_status": "safe",
                    "events": [],
                },
                semantic_frame={"top_intent": "local_life", "task_type": "coupon_query", "semantic_source": "real_llm", "llm_backend": "real_llm"},
                session_state_after={"pending_clarification": {"type": "shop_choice", "reason": "ambiguous_candidates"}},
                answer_source="llm_verbalizer",
                answer_verify_passed=True,
                final_safety_status="safe",
            ),
        ),
        AgentResponse(
            answer_text="暂时没有查到这家店的有效信息，请确认店名或换一个附近商家试试。",
            trace_id="trace_empty",
            session_id="sid2",
            debug=DebugInfo(
                execution_trace=[],
                turn_trace={
                    "trace_id": "trace_empty",
                    "session_id": "sid2",
                    "turn_id": "turn_1",
                    "user_text": "不存在的店有券吗",
                    "top_intent": "local_life",
                    "semantic_source": "real_llm",
                    "llm_backend": "real_llm",
                    "llm_backend_kind": "real_llm",
                    "llm_backend_family": "real_llm",
                    "tool_backend": "java_api",
                    "llm_called": True,
                    "task_type": "coupon_query",
                    "primary_task": "coupon_query",
                    "selected_flow": "single_shop_query_flow",
                    "target_status": "NOT_FOUND",
                    "reference_resolution_source": "semantic_frame",
                    "candidate_count": 0,
                    "decision_type": "single_shop",
                    "tool_call_count": 1,
                    "answer_source": "llm_verbalizer",
                    "answer_verify_passed": True,
                    "answer_verify_violations": [],
                    "rewrite_count": 0,
                    "fallback_reason": "",
                    "fallback_used": False,
                    "legacy_used": False,
                    "evidence_incomplete": False,
                    "final_safety_status": "safe",
                    "events": [],
                },
                semantic_frame={"top_intent": "local_life", "task_type": "coupon_query", "semantic_source": "real_llm", "llm_backend": "real_llm"},
                tool_results={},
                answer_source="llm_verbalizer",
                answer_verify_passed=True,
                final_safety_status="safe",
            ),
        ),
    ]
    calls = {"index": 0}

    def fake_run_agent(text, session_id=""):
        item = responses[calls["index"]]
        calls["index"] += 1
        return item

    monkeypatch.setattr(run_eval_module, "run_agent_graph", fake_run_agent)
    report = run_eval(
        [
            {
                "case_id": "clarify_ok",
                "category": "real_e2e_acceptance",
                "turns": [{"user": "海底捞有券吗"}],
                "expected": {
                    "expect_llm_backend_kind": "real_llm",
                    "forbid_semantic_sources": ["fallback_rules", "rule_based"],
                    "forbid_tool_backends": ["mock", "fake", "stub"],
                    "expect_answer_source": "llm_verbalizer",
                    "forbid_answer_sources": ["template", "template_fallback"],
                    "expect_legacy_used": False,
                    "expect_fallback_used": False,
                    "expect_evidence_incomplete": False,
                    "expect_terminal": "clarify",
                    "require_clarify_on_ambiguous_candidates": True,
                },
            },
            {
                "case_id": "trusted_failure_ok",
                "category": "real_e2e_acceptance",
                "turns": [{"user": "不存在的店有券吗"}],
                "expected": {
                    "expect_llm_backend_kind": "real_llm",
                    "forbid_semantic_sources": ["fallback_rules", "rule_based"],
                    "forbid_tool_backends": ["mock", "fake", "stub"],
                    "expect_answer_source": "llm_verbalizer",
                    "forbid_answer_sources": ["template", "template_fallback"],
                    "expect_legacy_used": False,
                    "expect_fallback_used": False,
                    "expect_evidence_incomplete": False,
                    "expect_terminal": "trusted_failure",
                    "require_trusted_failure_on_empty_tools": True,
                    "require_tool_results": False,
                },
            },
        ],
        backend="real_llm",
        write_reports=False,
    )
    assert report["summary"]["passed"] == 2
