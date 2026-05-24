from __future__ import annotations

import re
from pathlib import Path
import unittest

import _bootstrap  # noqa: F401


class LegacyRoutingPurgeTestCase(unittest.TestCase):
    def test_core_runtime_files_do_not_branch_on_legacy_routing_fields(self) -> None:
        root = Path(__file__).resolve().parents[1]
        targets = [
            root / "src" / "learning_agent_service" / "application" / "routing.py",
            root / "src" / "learning_agent_service" / "application" / "dependencies.py",
            root / "src" / "learning_agent_service" / "application" / "workflow" / "adapters.py",
            root / "src" / "learning_agent_service" / "application" / "workflow" / "subgraphs.py",
            root / "src" / "learning_agent_service" / "tools" / "service.py",
            root / "src" / "learning_agent_service" / "memory" / "orchestrator.py",
        ]
        patterns = [
            re.compile(r"\bif\b.*\.route_decision\b"),
            re.compile(r"\bif\b.*\.route_reason\b"),
            re.compile(r"\bif\b.*\.direct_response_kind\b"),
            re.compile(r"\bif\b.*\.proceed_to_understanding\b"),
            re.compile(r"\bif\b.*\.decision\b"),
            re.compile(r"\bif\b.*\.slots\b"),
            re.compile(r"\bif\b.*\bTurnDecision\b"),
            re.compile(r"\bif\b.*\bshould_run_retrieval\b"),
            re.compile(r"\bif\b.*\brequires_retrieval\b"),
        ]

        violations: list[str] = []
        for path in targets:
            text = path.read_text(encoding="utf-8")
            for index, line in enumerate(text.splitlines(), start=1):
                if not line.lstrip().startswith("if "):
                    continue
                for pattern in patterns:
                    if pattern.search(line):
                        violations.append(f"{path}:{index}:{line.strip()}")

        self.assertEqual(violations, [], msg="Legacy routing branches still present:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
