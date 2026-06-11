from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
REPO_ROOT = TESTS_DIR.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(REPO_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.builder import (
    describe_langgraph_topology,
    export_full_langgraph_mermaid,
    export_langgraph_mermaid,
)


EDGE_RE = re.compile(
    r"^(?P<source>[A-Za-z0-9_]+\[[^\]]+\]|[A-Za-z0-9_]+\{[^\}]+\}|[A-Za-z0-9_]+\([^\)]+\)|[A-Za-z0-9_?]+)"
    r"\s*-->(?:\|(?P<label>[^|]+)\|)?\s*"
    r"(?P<target>[A-Za-z0-9_]+\[[^\]]+\]|[A-Za-z0-9_]+\{[^\}]+\}|[A-Za-z0-9_]+\([^\)]+\)|[A-Za-z0-9_?]+)$"
)


def _node_label(token: str) -> str:
    token = token.strip()
    for pattern in (
        r"^[A-Za-z0-9_]+\[([^\]]+)\]$",
        r"^[A-Za-z0-9_]+\{([^\}]+)\}$",
        r"^[A-Za-z0-9_]+\(([^\)]+)\)$",
    ):
        match = re.match(pattern, token)
        if match:
            label = match.group(1).strip()
            if label.lower() == "start":
                return "START"
            if label.lower() == "end":
                return "END"
            return label
    if token.lower() == "start":
        return "START"
    if token.lower() == "end":
        return "END"
    return token


def _sanitize_node_id(label: str) -> str:
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in label).strip("_")
    return safe or "node"


def _parse_mermaid_topology(text: str) -> tuple[str | None, str | None, list[str], list[tuple[str, str, str | None]]]:
    alias_map: dict[str, str] = {}
    alias_pattern = re.compile(
        r"(?P<alias>[A-Za-z0-9_]+)\[(?P<label>[^\]]+)\]|(?P<brace_alias>[A-Za-z0-9_]+)\{(?P<brace_label>[^\}]+)\}|(?P<paren_alias>[A-Za-z0-9_]+)\((?P<paren_label>[^\)]+)\)"
    )
    for raw_line in text.splitlines():
        for match in alias_pattern.finditer(raw_line):
            alias = match.group("alias") or match.group("brace_alias") or match.group("paren_alias")
            label = match.group("label") or match.group("brace_label") or match.group("paren_label")
            label = label.strip()
            if label.lower() == "start":
                alias_map[alias] = "START"
            elif label.lower() == "end":
                alias_map[alias] = "END"
            else:
                alias_map[alias] = label

    nodes: list[str] = []
    node_seen: set[str] = set()
    edges: list[tuple[str, str, str | None]] = []
    entry_point = None
    terminal = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%") or line.startswith("flowchart") or line.startswith("graph TD"):
            continue
        if "-->" not in line:
            continue
        match = EDGE_RE.match(line)
        if not match:
            continue
        source_token = match.group("source").strip()
        target_token = match.group("target").strip()
        source = alias_map.get(source_token, _node_label(source_token))
        target = alias_map.get(target_token, _node_label(target_token))
        if source.lower() == "start":
            source = "START"
        if target.lower() == "end":
            target = "END"
        label = match.group("label")
        label = label.strip() if label is not None else None
        edges.append((source, target, label))
        for node in (source, target):
            if node.lower() in {"start", "end"}:
                continue
            if node not in node_seen:
                node_seen.add(node)
                nodes.append(node)
        if source.lower() == "start":
            entry_point = target
        if target.lower() == "end":
            terminal = "END"
    return entry_point, terminal, nodes, edges


class ArcCoreTopologyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.arc_core_text = (REPO_ROOT / "todo" / "arc_core.md").read_text(encoding="utf-8")
        cls.doc_entry_point, cls.doc_terminal, cls.doc_nodes, cls.doc_edges = _parse_mermaid_topology(cls.arc_core_text)
        cls.canonical = describe_langgraph_topology()

    def test_canonical_topology_matches_arc_core(self) -> None:
        self.assertEqual(self.canonical["entry_point"], self.doc_entry_point)
        self.assertEqual(self.canonical["terminal"], self.doc_terminal)
        self.assertEqual(set(self.canonical["nodes"]), set(self.doc_nodes))

        canonical_edges = {
            (edge["source"], edge["target"], edge.get("label"))
            for edge in self.canonical["edges"]
        }
        self.assertEqual(canonical_edges, set(self.doc_edges))

    def test_export_langgraph_mermaid_matches_canonical_topology(self) -> None:
        mermaid = export_langgraph_mermaid()
        _, _, nodes, edges = _parse_mermaid_topology(mermaid)

        self.assertEqual(set(nodes), set(self.canonical["nodes"]))
        self.assertEqual(
            {(source, target, label) for source, target, label in edges},
            {
                (edge["source"], edge["target"], edge.get("label"))
                for edge in self.canonical["edges"]
            },
        )

    def test_export_full_langgraph_mermaid_contains_main_graph_contract(self) -> None:
        mermaid = export_full_langgraph_mermaid()

        for node in self.canonical["nodes"]:
            node_id = f"main_{_sanitize_node_id(node)}"
            self.assertIn(f"    {node_id}[{node}]", mermaid)

        for edge in self.canonical["edges"]:
            source = f"main_{_sanitize_node_id(edge['source'])}"
            target = f"main_{_sanitize_node_id(edge['target'])}"
            label = edge.get("label")
            if label:
                self.assertIn(f"  {source} -->|{label}| {target}", mermaid)
            else:
                self.assertIn(f"  {source} --> {target}", mermaid)


if __name__ == "__main__":
    unittest.main()
