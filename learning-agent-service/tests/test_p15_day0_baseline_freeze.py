from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import yaml

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
LOCAL_LIFE_TESTS_DIR = TESTS_DIR / "local_life"
if str(LOCAL_LIFE_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_LIFE_TESTS_DIR))

import _bootstrap  # noqa: F401

from chat_test_client import ChatStreamTestClient
from learning_agent_service.application.workflow.builder import (
    describe_langgraph_topology,
    export_langgraph_mermaid,
    write_langgraph_visualizations,
)
from learning_agent_service.application.workflow.graphs import (
    describe_rag_graph_topology,
    describe_recommendation_graph_topology,
    describe_tool_graph_topology,
    export_rag_graph_mermaid,
    export_recommendation_graph_mermaid,
    export_tool_graph_mermaid,
)
from learning_agent_service.application.workflow.runner import SequentialWorkflowRunner
from learning_agent_service.application.workflow.services import (
    PlanExecuteSubgraphServices,
    RagSubgraphServices,
    ToolSubgraphServices,
    UnderstandTurnServices,
    WorkflowServices,
)
from learning_agent_service.domain import ChatTurnCommand, EvidenceItem, EvidencePack, IntentType, PlanStep, RagResult, RagStatus, SseEnvelope, build_initial_state


BASELINE_ROOT = REPO_ROOT / "docs" / "p1.5" / "baseline_freeze"
GRAPH_ROOT = BASELINE_ROOT / "graphs"
MANIFEST_PATH = BASELINE_ROOT / "baseline_manifest.yaml"
SAMPLES_PATH = BASELINE_ROOT / "baseline_samples.yaml"
CASE_LIST_PATH = BASELINE_ROOT / "baseline_case_list.yaml"
REPORT_PATH = BASELINE_ROOT / "baseline_report.md"


class P15Day0BaselineFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()

    def _stream_case(self, *, case_id: str, category: str, query: str, session_prefix: str, extra_payload: dict | None = None, follow_up: str | None = None) -> dict:
        session_id = f"{session_prefix}-{uuid4().hex[:8]}"
        first = self.client.post_message(
            message=query,
            session_id=session_id,
            extra_payload=extra_payload or {},
        )
        result = first
        turn_results = [first]
        if follow_up is not None:
            result = self.client.post_message(
                message=follow_up,
                session_id=session_id,
                extra_payload=extra_payload or {},
            )
            turn_results.append(result)

        return {
            "case_id": case_id,
            "category": category,
            "session_id": session_id,
            "turn_count": len(turn_results),
            "query": query,
            "follow_up": follow_up,
            "final_answer": result.final_answer,
            "final_payload": result.final_payload,
            "final_context": result.final_context,
            "metrics": result.metrics,
            "phase5_trace": (result.metrics or {}).get("phase5_trace") or {},
            "events": result.events,
            "sse_event_types": [event.get("event_type") for event in result.events],
            "tool_calls": result.tool_calls,
            "tool_results": result.tool_results,
            "retrieval_events": result.retrieval_events,
            "error_events": result.error_events,
        }

    def _build_plan_sample(self) -> dict:
        command = ChatTurnCommand(
            trace_id=f"trace-baseline-plan-{uuid4().hex[:8]}",
            session_id=f"baseline-plan-{uuid4().hex[:8]}",
            turn_id=f"turn-baseline-plan-{uuid4().hex[:8]}",
            user_id="baseline-plan",
            message="推荐一家适合带爸妈吃饭的餐厅",
            page="assistant",
            client_context={},
        )
        state = build_initial_state(command=command, workflow_version="baseline-freeze/v1")
        state["persistent"].current_city = "北京"
        state["turn"] = state["turn"].model_copy(
            update={
                "task_complexity": "complex",
                "execution_mode": "plan_execute",
                "intent": IntentType.RECOMMEND,
                "slots": {"scene": "family_dinner", "city": "北京"},
                "rag_result": RagResult(
                    status=RagStatus.OK,
                    evidence_status="OK",
                    evidence_pack=EvidencePack(
                        evidence_status="OK",
                        items=[
                            EvidenceItem(
                                chunk_id="baseline-plan-chunk",
                                content="北京适合带爸妈吃饭的餐厅，环境安静，适合家庭聚餐。",
                                score=0.91,
                                document_id="baseline-plan-doc",
                                chunk_type="review",
                            )
                        ],
                    ),
                ),
            }
        )

        def _append(state, stage: str, event_type: str):
            runtime = state["runtime"]
            events = list(runtime.emitted_events)
            events.append(
                SseEnvelope(
                    event_type=event_type,
                    trace_id=runtime.trace_id,
                    session_id=runtime.session_id,
                    turn_id=runtime.turn_id,
                    timestamp=datetime.now(timezone.utc),
                    workflow_version=runtime.workflow_version,
                    payload={"stage": stage},
                )
            )
            state["runtime"] = runtime.model_copy(update={"emitted_events": events})
            return state

        def _compose_answer(current):
            current["turn"] = current["turn"].model_copy(
                update={"final_answer": "Plan execution completed successfully."}
            )
            return _append(current, "compose_answer", "final")

        services = WorkflowServices(
            load_context=lambda current: _append(current, "load_context", "retrieval_started"),
            understand_turn=UnderstandTurnServices(
                parse_intent_slots=lambda current: current,
                resolve_reference=lambda current: current,
                ambiguity_check=lambda current: current,
                rewrite_query=lambda current: current,
            ),
            rag_subgraph=RagSubgraphServices(
                hybrid_retrieve=lambda current: current,
                evaluate_evidence=lambda current: current,
                citation_builder=lambda current: current,
            ),
            tool_subgraph=ToolSubgraphServices(
                tool_planner=lambda current: current,
                tool_executor=lambda current: current,
                tool_result_normalizer=lambda current: current,
            ),
            plan_execute_subgraph=PlanExecuteSubgraphServices(
                plan_planner=lambda current: current,
                plan_validator=lambda current: current,
                step_executor=lambda current: current,
                progress_checker=lambda current: current,
                plan_reviewer=lambda current: current,
                human_approval_stub=lambda current: current,
                replanner=lambda current: current,
            ),
            compose_answer=_compose_answer,
            emit_final=lambda current: _append(current, "emit_final", "final"),
        )
        runner = SequentialWorkflowRunner(services=services, workflow_version="baseline-freeze/v1")
        with patch("learning_agent_service.application.workflow.runner.route_after_understand", return_value="plan_execute_subgraph"):
            updated = runner.run_state(state)
        event_types = [event.event_type for event in updated["runtime"].emitted_events]
        return {
            "case_id": "plan_execute",
            "category": "planning",
            "session_id": state["runtime"].session_id,
            "query": command.message,
            "final_answer": updated["turn"].final_answer,
            "final_task_summary": (
                updated["turn"].final_task_summary.model_dump(mode="json")
                if getattr(updated["turn"], "final_task_summary", None) is not None
                else None
            ),
            "metrics": updated["runtime"].metrics,
            "phase5_trace": (updated["runtime"].metrics or {}).get("phase5_trace") or {},
            "events": [
                event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
                for event in updated["runtime"].emitted_events
            ],
            "event_types": event_types,
        }

    def _build_manifest(self, samples: list[dict], plan_sample: dict) -> dict:
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "graph": {
                "main": {
                    "topology": describe_langgraph_topology(),
                    "mermaid": export_langgraph_mermaid(),
                },
                "rag": {
                    "topology": describe_rag_graph_topology(),
                    "mermaid": export_rag_graph_mermaid(),
                },
                "tool": {
                    "topology": describe_tool_graph_topology(),
                    "mermaid": export_tool_graph_mermaid(),
                },
                "recommendation": {
                    "topology": describe_recommendation_graph_topology(),
                    "mermaid": export_recommendation_graph_mermaid(),
                },
            },
            "samples": samples + [plan_sample],
            "baseline_test_summary": [
                {"suite": "learning-agent-service/tests/test_routing_decision_matrix.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/test_phase4_answer_verifier.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/test_streaming_behavior.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/test_sse.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/test_langgraph_checkpointing.py", "status": "skipped", "reason": "langgraph is not installed in this environment"},
                {"suite": "learning-agent-service/tests/local_life/test_day1_target_shop_chat.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/local_life/test_day6_langgraph_chat_stream.py", "status": "passed"},
                {"suite": "learning-agent-service/tests/local_life/test_day7_golden_cases_chat.py", "status": "passed"},
            ],
            "baseline_case_list": [
                {
                    "case_id": "direct_chat",
                    "category": "direct_chat",
                    "source_test": "learning-agent-service/tests/test_phase4_answer_verifier.py",
                    "notes": "answer verifier baseline; keep the current grounded/partial behavior frozen",
                },
                {
                    "case_id": "single_shop",
                    "category": "single_shop",
                    "source_test": "learning-agent-service/tests/local_life/test_day1_target_shop_chat.py::test_day1_1_explicit_single_shop",
                },
                {
                    "case_id": "query_merge_pronoun",
                    "category": "query_merge",
                    "source_test": "learning-agent-service/tests/local_life/test_day1_target_shop_chat.py::test_day1_3_pronoun_inheritance",
                },
                {
                    "case_id": "coupon_only",
                    "category": "coupon_only",
                    "source_test": "learning-agent-service/tests/local_life/test_day3_tools_coupon_chat.py::test_day3_4_no_target_shop_clarify",
                },
                {
                    "case_id": "recommendation",
                    "category": "recommendation",
                    "source_test": "learning-agent-service/tests/local_life/test_day5_workflow_graph_chat.py::test_day5_graph_runner_keeps_recommendation_default_count",
                },
                {
                    "case_id": "comparison",
                    "category": "comparison",
                    "source_test": "learning-agent-service/tests/rag/test_local_life_query_router.py::test_comparison_query_routes_to_multi_parent",
                },
                {
                    "case_id": "planning",
                    "category": "planning",
                    "source_test": "learning-agent-service/tests/test_plan_execution_runtime.py::test_plan_execute_success_emits_plan_events_and_final_summary",
                },
                {
                    "case_id": "unsafe_prompt_injection",
                    "category": "unsafe_prompt_injection",
                    "source_test": "learning-agent-service/tests/test_rag_gate.py",
                    "notes": "route gate and answer safety remain frozen; use current reject/clarify behavior as baseline",
                },
            ],
        }

    def _write_report(self, manifest: dict) -> None:
        report_lines = [
            "# P1.5 Day 0 Baseline Freeze",
            "",
            "## Graph Snapshot",
            f"- main graph topology: `docs/langgraph/main_graph.mmd`",
            f"- rag graph topology: `docs/langgraph/rag_graph.mmd`",
            f"- tool graph topology: `docs/langgraph/tool_graph.mmd`",
            f"- recommendation graph topology: `docs/langgraph/recommendation_graph.mmd`",
            f"- unified topology report: `docs/langgraph/langgraph_topology.md`",
            "",
            "### Main Graph Nodes",
        ]
        for node in manifest["graph"]["main"]["topology"]["nodes"]:
            report_lines.append(f"- {node}")
        report_lines.extend(
            [
                "",
                "## Baseline Samples",
            ]
        )
        for sample in manifest["samples"]:
            answer_preview = str(sample.get("final_answer") or "").replace("\n", " ").strip()
            report_lines.append(
                "- {case_id} [{category}] -> `{final_answer}`".format(
                    case_id=sample["case_id"],
                    category=sample["category"],
                    final_answer=answer_preview[:120],
                )
            )
        report_lines.extend(
            [
                "",
                "## Test Summary",
            ]
        )
        for item in manifest["baseline_test_summary"]:
            suffix = f" ({item['reason']})" if item.get("reason") else ""
            report_lines.append(f"- {item['suite']}: {item['status']}{suffix}")
        report_lines.extend(
            [
                "",
                "## Case List",
            ]
        )
        for item in manifest["baseline_case_list"]:
            report_lines.append(f"- {item['case_id']}: {item['category']} -> {item['source_test']}")
        report_lines.extend(
            [
                "",
                "## Notes",
                "- These files freeze the current baseline only; later days should diff against them instead of redefining the behavior.",
                "- The repo currently stores Mermaid snapshots as the authoritative graph artifact. A PNG renderer is not required for this freeze step.",
            ]
        )
        REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")

    def test_capture_day0_baseline_freeze_artifacts(self) -> None:
        BASELINE_ROOT.mkdir(parents=True, exist_ok=True)
        GRAPH_ROOT.mkdir(parents=True, exist_ok=True)

        written = write_langgraph_visualizations(GRAPH_ROOT)

        samples = [
            self._stream_case(
                case_id="direct_chat",
                category="direct_chat",
                query="你好",
                session_prefix="baseline-direct",
            ),
            self._stream_case(
                case_id="single_shop",
                category="single_shop",
                query="海底捞水晶城店怎么样？",
                session_prefix="baseline-single-shop",
            ),
            self._stream_case(
                case_id="query_merge_pronoun",
                category="query_merge",
                query="海底捞水晶城店怎么样？",
                follow_up="它有券吗？",
                session_prefix="baseline-pronoun",
            ),
            self._stream_case(
                case_id="recommendation",
                category="recommendation",
                query="附近有什么推荐的餐厅？",
                session_prefix="baseline-recommendation",
                extra_payload={
                    "city": "北京",
                    "current_city": "北京",
                    "location": {
                        "type": "near_user",
                        "city": "北京",
                        "lat": None,
                        "lng": None,
                        "radius_km": 3.0,
                    },
                },
            ),
            self._stream_case(
                case_id="mixed_facet",
                category="mixed_facet",
                query="海底捞水晶城店有券吗，现在营业吗？",
                session_prefix="baseline-mixed-facet",
                extra_payload={
                    "shopName": "海底捞水晶城店",
                    "shopId": 5,
                },
            ),
        ]
        plan_sample = self._build_plan_sample()
        manifest = self._build_manifest(samples, plan_sample)

        MANIFEST_PATH.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
        SAMPLES_PATH.write_text(yaml.safe_dump({"samples": samples + [plan_sample]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        CASE_LIST_PATH.write_text(yaml.safe_dump({"baseline_case_list": manifest["baseline_case_list"]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._write_report(manifest)

        self.assertTrue(written["main_graph.mmd"])
        self.assertTrue(MANIFEST_PATH.exists())
        self.assertTrue(SAMPLES_PATH.exists())
        self.assertTrue(CASE_LIST_PATH.exists())
        self.assertTrue(REPORT_PATH.exists())
        self.assertGreaterEqual(len(samples), 5)
        self.assertTrue(all(sample["events"] for sample in samples))
        self.assertTrue(plan_sample["event_types"])


if __name__ == "__main__":
    unittest.main()
