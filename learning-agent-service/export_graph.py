from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from learning_agent_service.application.workflow.builder import write_langgraph_visualizations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export LangGraph visualizations for the current workflow.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the exported graph artifacts. Defaults to docs/langgraph.",
    )
    args = parser.parse_args(argv)

    written = write_langgraph_visualizations(output_dir=args.output_dir)
    for filename, path in sorted(written.items()):
        print(f"{filename}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
