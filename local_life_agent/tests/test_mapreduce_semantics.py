from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_discovery_decision_uses_batch_execution_not_langgraph_send() -> None:
    graph_builder = _read("local_life_agent/engine/graph_builder.py")
    execution_review = _read("local_life_agent/engine/subgraphs/execution_review_subgraph.py")
    gateway = _read("local_life_agent/tools/gateway.py")
    graph_state = _read("local_life_agent/domain/graph_state.py")

    assert "from langgraph.graph import Send" not in graph_builder
    assert "Send(" not in graph_builder
    assert "Send(" not in execution_review
    assert "class BatchToolExecutor" in gateway
    assert "asyncio.gather" in gateway
    assert "tool_result_set: dict[str, ToolResult]" in graph_state
    assert "tool_result_set: Annotated" not in graph_state
    assert "evidence_pack: Optional[EvidencePack]" in graph_state

