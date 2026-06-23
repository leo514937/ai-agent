from __future__ import annotations

import json
import importlib

from local_life_agent.agent import AgentResponse, DebugInfo
from local_life_agent.eval.run_eval import load_cases, run_eval, run_eval_file


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
    monkeypatch.delenv("LLM_API_KEY", raising=False)
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
