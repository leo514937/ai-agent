"""Phase 1 architecture boundary tests.

These tests freeze the current compatibility surface so new code cannot
silently expand deprecated import paths.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "local_life_agent"

CORE_COMPAT_ALLOWED_CALLERS = {
    "local_life_agent/engine/subgraphs/execution_review_subgraph.py",
    "local_life_agent/engine/subgraphs/planning_subgraph.py",
    "local_life_agent/engine/subgraphs/state_update_plan.py",
    "local_life_agent/input/receiver.py",
    "local_life_agent/planning/evidence/tool_batch_executor.py",
    "local_life_agent/planning/shared/evidence_adapter.py",
}

CORE_COMPAT_SOURCE_DIR = "local_life_agent/core/"

PLANNING_SHIM_ALLOWED_CALLERS = {
    "local_life_agent/domain/decision.py",
    "local_life_agent/domain/evidence.py",
    "local_life_agent/domain/goal.py",
    "local_life_agent/engine/_routes.py",
    "local_life_agent/engine/subgraphs/orchestration_router_shadow.py",
}

PLANNING_SHIM_FILES = {
    "local_life_agent/planning/candidate_review.py",
    "local_life_agent/planning/comparison_planner.py",
    "local_life_agent/planning/decision_planner.py",
    "local_life_agent/planning/decision_review.py",
    "local_life_agent/planning/evidence_planner.py",
    "local_life_agent/planning/evidence_review.py",
    "local_life_agent/planning/execution_plan_builder.py",
    "local_life_agent/planning/facet_planner.py",
    "local_life_agent/planning/goal_draft.py",
    "local_life_agent/planning/goal_planner.py",
    "local_life_agent/planning/goal_review.py",
    "local_life_agent/planning/plan_validator.py",
    "local_life_agent/planning/ranking_policy.py",
    "local_life_agent/planning/replan_policy.py",
    "local_life_agent/planning/review_policy.py",
    "local_life_agent/planning/state_update_planner.py",
}

GRAPH_BUILDER_ALLOWED_CALLERS = {
    "local_life_agent/agent.py",
    "local_life_agent/core/candidate_core.py",
    "local_life_agent/engine/__init__.py",
    "local_life_agent/engine/subgraphs/execution_review_subgraph.py",
    "local_life_agent/engine/subgraphs/intake_guard_router.py",
    "local_life_agent/engine/subgraphs/planning_subgraph.py",
    "local_life_agent/engine/subgraphs/response_subgraph.py",
    "local_life_agent/engine/subgraphs/top_intent_router_handler.py",
    "local_life_agent/engine/subgraphs/understanding_subgraph.py",
    "local_life_agent/engine/workflows/deterministic_tool_workflow.py",
    "local_life_agent/target/candidate_resolver.py",
    "local_life_agent/target/reference_resolver.py",
}

GRAPH_BUILDER_MODULE = "local_life_agent.engine.graph_builder"
PLANNING_SHIM_MODULES = {
    "local_life_agent.planning.candidate_review",
    "local_life_agent.planning.comparison_planner",
    "local_life_agent.planning.decision_planner",
    "local_life_agent.planning.decision_review",
    "local_life_agent.planning.evidence_planner",
    "local_life_agent.planning.evidence_review",
    "local_life_agent.planning.execution_plan_builder",
    "local_life_agent.planning.facet_planner",
    "local_life_agent.planning.goal_draft",
    "local_life_agent.planning.goal_planner",
    "local_life_agent.planning.goal_review",
    "local_life_agent.planning.plan_validator",
    "local_life_agent.planning.ranking_policy",
    "local_life_agent.planning.replan_policy",
    "local_life_agent.planning.review_policy",
    "local_life_agent.planning.state_update_planner",
}


def _resolve_module(package: str, node: ast.ImportFrom) -> str:
    module = node.module or ""
    if node.level:
        try:
            return importlib.util.resolve_name("." * node.level + module, package)
        except ValueError:
            return module
    return module


def _iter_production_files():
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        yield path


def _scan_import_targets(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    package = ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])
    targets: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved = _resolve_module(package, node)
            for alias in node.names:
                if resolved == "local_life_agent.engine" and alias.name == "graph_builder":
                    targets.add(GRAPH_BUILDER_MODULE)
                elif resolved:
                    targets.add(resolved)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)

    if 'import_module("local_life_agent.engine.graph_builder")' in text:
        targets.add(GRAPH_BUILDER_MODULE)

    return targets


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_phase1_docs_contain_frozen_paths_and_status_markers():
    analysis = (ROOT / "todo" / "architecture_overlap_analysis.md").read_text(encoding="utf-8")
    canonical_doc = (ROOT / "todo" / "architecture_phase1_canonical_import_paths.md").read_text(encoding="utf-8")
    report = (ROOT / "todo" / "architecture_phase1_canonical_path_freeze_report.md").read_text(encoding="utf-8")

    assert "architecture_phase1_canonical_path_freeze_report.md" in analysis
    assert "architecture_phase1_canonical_import_paths.md" in analysis
    assert "DEPRECATED_COMPAT" in canonical_doc
    assert "CANONICAL" in canonical_doc
    assert "NEEDS_DECISION" in canonical_doc
    assert "TEST_ONLY" in canonical_doc
    assert "LEGACY_REMOVE_IN_PHASE6" in canonical_doc
    assert "PASS" in report
    assert "可以进入 Phase 2" in report


def test_phase1_core_compat_imports_remain_allowlisted():
    violations: list[str] = []
    for path in _iter_production_files():
        rel = _rel(path)
        if rel in CORE_COMPAT_ALLOWED_CALLERS or rel.startswith(CORE_COMPAT_SOURCE_DIR):
            continue
        for target in _scan_import_targets(path):
            if target.startswith("local_life_agent.core"):
                violations.append(f"{rel} -> {target}")

    assert not violations, "core 兼容面出现了未允许的新调用:\n" + "\n".join(sorted(violations))


def test_phase1_planning_shim_imports_remain_allowlisted():
    violations: list[str] = []
    for path in _iter_production_files():
        rel = _rel(path)
        if rel in PLANNING_SHIM_ALLOWED_CALLERS or rel in PLANNING_SHIM_FILES:
            continue
        for target in _scan_import_targets(path):
            if target in PLANNING_SHIM_MODULES:
                violations.append(f"{rel} -> {target}")

    assert not violations, "planning 顶层 shim 出现了未允许的新调用:\n" + "\n".join(sorted(violations))


def test_phase1_graph_builder_surface_remains_frozen():
    violations: list[str] = []
    for path in _iter_production_files():
        rel = _rel(path)
        if rel == "local_life_agent/engine/graph_builder.py":
            continue
        for target in _scan_import_targets(path):
            if target == GRAPH_BUILDER_MODULE:
                if rel not in GRAPH_BUILDER_ALLOWED_CALLERS:
                    violations.append(f"{rel} -> {target}")

    assert not violations, "graph_builder 兼容面检查失败:\n" + "\n".join(sorted(violations))
