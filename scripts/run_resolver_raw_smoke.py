"""Raw-result smoke for resolver/search candidate extraction.

This script exercises the real tool backend and CandidateResolver
without invoking the full agent graph.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_life_agent.domain.candidate import CandidateSource, CandidateSpec, GoalType, LocalLifeGoalDraft
from local_life_agent.target.candidate_resolver import CandidateResolver
from local_life_agent.tools.gateway import dispatch_tool_call


CASES = [
    ("resolve_shop", {"query": "海底捞"}),
    ("resolve_shop", {"query": "海底捞水晶城店"}),
    ("resolve_shop", {"query": "山城一锅"}),
    ("search_shops", {"query": "火锅"}),
    ("search_shops", {"query": "附近 火锅"}),
    ("search_shops", {"query": "约会 火锅"}),
]


def _candidate_info(candidate_set) -> dict[str, object]:
    candidates = list(candidate_set.candidates or [])
    return {
        "normalized_candidate_count": len(candidates),
        "candidate_ids": [c.shop_id for c in candidates],
        "candidate_names": [c.shop_name for c in candidates],
        "status": candidate_set.status.value if hasattr(candidate_set.status, "value") else str(candidate_set.status),
    }


def main() -> int:
    resolver = CandidateResolver()
    rows: list[dict[str, object]] = []

    for tool_name, payload in CASES:
        raw = dispatch_tool_call(tool_name, payload)
        data = raw.get("data")
        if isinstance(data, list):
            raw_result_count = len(data)
            raw_sample = data[:2]
        elif isinstance(data, dict):
            status = str(data.get("status", "") or "")
            if status == "RESOLVED":
                raw_result_count = 1
                raw_sample = [data.get("shop")] if data.get("shop") else []
            else:
                raw_result_count = len(data.get("candidates", []) or [])
                raw_sample = (data.get("candidates", []) or [])[:2]
        else:
            raw_result_count = 0
            raw_sample = None

        if tool_name == "resolve_shop":
            goal = LocalLifeGoalDraft(goal_type=GoalType.SINGLE_SHOP_QUERY, candidate_source=CandidateSource.EXPLICIT)
            spec = CandidateSpec(source=CandidateSource.EXPLICIT, explicit_mentions=[payload["query"]], limit=3)
        else:
            goal = LocalLifeGoalDraft(goal_type=GoalType.RECOMMENDATION, candidate_source=CandidateSource.DISCOVERY, candidate_limit=3)
            spec = CandidateSpec(source=CandidateSource.DISCOVERY, query=payload["query"], limit=3)

        candidate_set = resolver.resolve(goal, spec)
        rows.append(
            {
                "tool_name": tool_name,
                "input": payload["query"],
                "backend": raw.get("tool_backend") or raw.get("backend_source") or raw.get("source"),
                "raw_result_count": raw_result_count,
                "raw_result_sample": raw_sample,
                **_candidate_info(candidate_set),
                "error_type": raw.get("error_code"),
                "error_message": raw.get("error_message"),
            }
        )

    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
