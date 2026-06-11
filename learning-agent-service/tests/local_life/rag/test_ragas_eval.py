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
from learning_agent_service.rag.ragas_eval import (
    RagasEvalCase,
    build_ragas_rows,
    format_ragas_eval_report,
    select_ragas_metric_specs,
    summarize_ragas_observation,
    summarize_ragas_results,
)


class RagasEvalTestCase(unittest.TestCase):
    def test_build_ragas_rows_keeps_reference_and_contexts(self) -> None:
        case = RagasEvalCase.from_mapping(
            {
                "case_id": "single_shop_scene_fit_001",
                "query": "海底捞水晶城店适合约会吗？",
                "expected_route": "rag",
                "expected_rag_mode": "single_shop_rag",
                "expected_shop_id": 5,
                "reference": "海底捞水晶城店环境安静，氛围不错，适合约会。",
                "reference_contexts": ["环境安静，适合约会。", "氛围不错。"],
                "reference_context_ids": ["ctx-1", "ctx-2"],
            }
        )
        pack = build_evidence_pack(
            raw_query=case.query,
            ranked_candidates=[{"shop_id": 5, "name": "海底捞水晶城店"}],
            evidence_claims=[
                {
                    "chunk_id": "e-5-1",
                    "shop_id": 5,
                    "claim": "环境安静，适合约会。",
                    "support_text": "环境安静，适合约会。",
                    "source_type": "scene_fit",
                    "confidence": 0.92,
                    "metadata": {"shop_id": 5},
                },
                {
                    "chunk_id": "e-5-2",
                    "shop_id": 5,
                    "claim": "氛围不错。",
                    "support_text": "氛围不错。",
                    "source_type": "environment",
                    "confidence": 0.87,
                    "metadata": {"shop_id": 5},
                },
            ],
            slots={"shop_id": 5, "rag_mode": "single_shop_rag"},
            source_summary={"rag_mode": "single_shop_rag"},
            safety_result={},
            rag_mode="single_shop_rag",
            target_shop_id=5,
        )
        observation = summarize_ragas_observation(
            case=case,
            response="海底捞水晶城店环境安静，氛围不错，适合约会。",
            metrics={"rag_mode": "single_shop_rag"},
            evidence_pack=pack,
        )

        rows = build_ragas_rows((case,), (observation,))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_input"], case.query)
        self.assertEqual(rows[0]["response"], "海底捞水晶城店环境安静，氛围不错，适合约会。")
        self.assertEqual(rows[0]["reference"], case.reference)
        self.assertEqual(rows[0]["retrieved_contexts"], ["环境安静，适合约会。", "氛围不错。"])
        self.assertEqual(rows[0]["retrieved_context_ids"], ["e-5-1", "e-5-2"])
        self.assertEqual(rows[0]["reference_contexts"], ["环境安静，适合约会。", "氛围不错。"])
        self.assertEqual(rows[0]["reference_context_ids"], ["ctx-1", "ctx-2"])

    def test_select_metric_specs_prefers_full_reference_metrics(self) -> None:
        rows = [
            {
                "user_input": "海底捞水晶城店适合约会吗？",
                "response": "适合约会。",
                "reference": "环境安静，适合约会。",
                "retrieved_contexts": ["环境安静，适合约会。"],
                "retrieved_context_ids": ["ctx-a"],
                "reference_contexts": ["环境安静，适合约会。"],
                "reference_context_ids": ["ctx-a"],
            }
        ]

        specs = select_ragas_metric_specs(rows, profile="full")
        names = {spec.name for spec in specs}

        self.assertTrue(
            {
                "answer_relevancy",
                "faithfulness",
                "context_precision",
                "context_recall",
                "context_entity_recall",
                "noise_sensitivity",
                "factual_correctness",
                "semantic_similarity",
                "bleu_score",
                "rouge_score",
                "string_presence",
                "exact_match",
                "chrf_score",
            }.issubset(names)
        )

    def test_select_metric_specs_without_reference_falls_back_to_context_utilization(self) -> None:
        rows = [
            {
                "user_input": "海底捞水晶城店适合约会吗？",
                "response": "适合约会。",
                "retrieved_contexts": ["环境安静，适合约会。"],
            }
        ]

        specs = select_ragas_metric_specs(rows, profile="full")
        names = {spec.name for spec in specs}

        self.assertIn("answer_relevancy", names)
        self.assertIn("faithfulness", names)
        self.assertIn("context_utilization", names)
        self.assertNotIn("context_recall", names)
        self.assertNotIn("context_precision", names)
        self.assertNotIn("noise_sensitivity", names)
        self.assertNotIn("factual_correctness", names)

    def test_summary_report_aggregates_metric_means(self) -> None:
        rows = [
            {"case_id": "case-1", "user_input": "q1", "response": "a1"},
            {"case_id": "case-2", "user_input": "q2", "response": "a2"},
        ]
        specs = select_ragas_metric_specs(
            [{"user_input": "q1", "response": "a1", "retrieved_contexts": ["c1"]}],
            profile="basic",
        )

        summary = summarize_ragas_results(
            rows=rows,
            score_rows=[
                {"answer_relevancy": 0.8, "faithfulness": 1.0},
                {"answer_relevancy": 0.6, "faithfulness": 0.5},
            ],
            metric_specs=specs,
            skipped_metrics=["context_recall"],
            evaluation_backend="ragas",
        )
        report = format_ragas_eval_report(summary)

        self.assertEqual(summary["case_count"], 2)
        self.assertAlmostEqual(summary["metric_means"]["answer_relevancy"], 0.7, places=6)
        self.assertAlmostEqual(summary["metric_means"]["faithfulness"], 0.75, places=6)
        self.assertEqual(summary["skipped_metrics"], ["context_recall"])
        self.assertIn("RAGAS Eval Report", report)
        self.assertIn("answer_relevancy", report)


if __name__ == "__main__":
    unittest.main()
