from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from learning_agent_service.rag.backfill import plan_knowledge_chunk_backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan a knowledge chunk payload backfill.")
    parser.add_argument("--payload", help="JSON payload to normalize.")
    parser.add_argument("--payload-file", help="Path to a JSON file containing the payload.")
    parser.add_argument("--json", action="store_true", help="Print the normalized plan as JSON.")
    args = parser.parse_args(argv)

    raw_payload = _load_payload(args.payload, args.payload_file)
    plan = plan_knowledge_chunk_backfill(json.loads(raw_payload.lstrip("\ufeff")))
    output = {
        "needs_backfill": plan.needs_backfill,
        "missing_fields": list(plan.missing_fields),
        "normalized_payload": plan.normalized_payload,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0


def _load_payload(payload: str | None, payload_file: str | None) -> str:
    if payload_file:
        return Path(payload_file).read_text(encoding="utf-8")
    if payload:
        return payload
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("请通过 --payload、--payload-file 或 stdin 提供 JSON payload")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
