from __future__ import annotations

import sys
import unittest
from pathlib import Path

LOCAL_LIFE_TESTS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(LOCAL_LIFE_TESTS_DIR), str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.evidence_pack import build_evidence_pack
from learning_agent_service.rag.local_life_eval import (
    evaluate_local_life_rag_cases,
    format_local_life_rag_eval_report,
    load_local_life_rag_eval_cases,
    summarize_local_life_rag_observation,
)


class RagEvalMetricsTestCase(unittest.TestCase):
    def test_eval_report_aggregates_case_metrics(self) -> None:
        cases_path = REPO_ROOT / "eval" / "local_life" / "rag_eval_cases.jsonl"
        cases = load_local_life_rag_eval_cases(cases_path)

        single_shop_case = next(case for case in cases if case.case_id == "single_shop_scene_fit_001")
        recommendation_case = next(case for case in cases if case.case_id == "recommendation_after_single_shop_anchor_001")

        single_shop_pack = build_evidence_pack(
            raw_query=single_shop_case.query,
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店"}],
            evidence_claims=[
                {"chunk_id": "e-5-1", "shop_id": 5, "claim": "环境安静，适合约会。", "support_text": "环境安静，适合约会。", "source_type": "scene_fit", "confidence": 0.92, "metadata": {"shop_id": 5}},
                {"chunk_id": "e-5-2", "shop_id": 5, "claim": "氛围不错。", "support_text": "氛围不错。", "source_type": "environment", "confidence": 0.87, "metadata": {"shop_id": 5}},
            ],
            slots={"shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={"rag_mode": "single_shop_rag"},
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )
        recommendation_pack = build_evidence_pack(
            raw_query=recommendation_case.query,
            ranked_candidates=[
                {"shop_id": 5, "name": "海底捞水晶城店"},
                {"shop_id": 9, "name": "新白鹿运河上街店"},
            ],
            evidence_claims=[
                {"chunk_id": "r-5-1", "shop_id": 5, "claim": "适合约会。", "support_text": "适合约会。", "source_type": "scene_fit", "confidence": 0.91, "metadata": {"shop_id": 5}},
                {"chunk_id": "r-5-2", "shop_id": 5, "claim": "有套餐可参考。", "support_text": "有套餐可参考。", "source_type": "package_description", "confidence": 0.88, "metadata": {"shop_id": 5}},
                {"chunk_id": "r-9-1", "shop_id": 9, "claim": "现在营业。", "support_text": "现在营业。", "source_type": "open_status", "confidence": 0.89, "metadata": {"shop_id": 9}},
            ],
            slots={"rag_mode": "recommendation_rag"},
            source_summary={"rag_mode": "recommendation_rag"},
            safety_result={},
            rag_mode="recommendation_rag",
        )

        observations = [
            summarize_local_life_rag_observation(
                case=single_shop_case,
                answer="海底捞水晶城店环境安静，适合约会，氛围不错。",
                metrics={
                    "rag_mode": "single_shop_rag",
                    "latest_turn_message": single_shop_case.query,
                    "route_gate": {"branch": "rag"},
                },
                evidence_pack=single_shop_pack,
            ),
            summarize_local_life_rag_observation(
                case=recommendation_case,
                answer="1. 海底捞水晶城店 2. 新白鹿运河上街店",
                metrics={
                    "rag_mode": "recommendation_rag",
                    "latest_turn_message": recommendation_case.turns[-1],
                    "route_gate": {"branch": "recommendation"},
                },
                evidence_pack=recommendation_pack,
            ),
        ]

        metrics = evaluate_local_life_rag_cases(cases, observations)
        report = format_local_life_rag_eval_report(metrics)

        self.assertEqual(metrics["case_count"], 3)
        self.assertEqual(metrics["matched_case_count"], 2)
        self.assertGreaterEqual(metrics["route_match_rate"], 1.0)
        self.assertGreaterEqual(metrics["rag_mode_match_rate"], 1.0)
        self.assertGreaterEqual(metrics["single_shop_isolation_rate"], 1.0)
        self.assertGreaterEqual(metrics["latest_turn_priority_rate"], 1.0)
        self.assertIn("Local Life RAG Eval Report", report)
        self.assertIn("recommendation_diversity", report)


if __name__ == "__main__":
    unittest.main()
