from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap  # noqa: F401

from learning_agent_service.local_life.response_builder import build_multi_shop_recommendation_answer, build_single_shop_review_answer
from learning_agent_service.local_life.response_builder.bundle import _merge_model_answer_once, build_response_bundle
from learning_agent_service.local_life.schemas import LocalLifeSlots


class _FakeCandidate(SimpleNamespace):
    def model_dump(self, mode: str = "json") -> dict:
        return {
            "shop_id": self.shop_id,
            "name": self.name,
            "shop_name": getattr(self, "shop_name", self.name),
            "structured_features": dict(self.structured_features),
            "evidence_features": dict(getattr(self, "evidence_features", {})),
            "vouchers": list(self.vouchers),
            "explainable_reasons": list(getattr(self, "explainable_reasons", [])),
            "matched_requirements": list(getattr(self, "matched_requirements", [])),
        }


class _FakeQualityResult(SimpleNamespace):
    def model_dump(self, mode: str = "json") -> dict:
        return dict(self.__dict__)


class _FakeSafetyResult(SimpleNamespace):
    def to_dict(self) -> dict:
        return {"answer_text": self.answer_text}


class BundleModelAnswerMergeTestCase(unittest.TestCase):
    def test_merge_model_answer_once_skips_equivalent_content(self) -> None:
        answer_text = "修正后的回答\n模型原文\n补充说明"

        merged = _merge_model_answer_once(
            answer_text,
            "模型原文",
            answer_contract=None,
            plan_usable=False,
            route_decision=None,
        )

        self.assertEqual(merged, answer_text)

    def test_build_response_bundle_merges_model_answer_only_once(self) -> None:
        candidate = _FakeCandidate(
            shop_id=1,
            name="海底捞水晶城店",
            shop_name="海底捞水晶城店",
            structured_features={"score": 4.8, "avg_price": 120, "distance_km": 1.2},
            evidence_features={},
            vouchers=[],
            explainable_reasons=["环境不错"],
            matched_requirements=[],
        )
        quality_result = _FakeQualityResult(
            final_answer="质量门修正后的回答",
            answer_style="single_shop_review",
            answer_depth_level="normal",
            answer_min_sections=3,
            answer_min_chars=80,
            clean_evidence_count=1,
            strong_evidence_count=1,
            medium_evidence_count=0,
            answer_char_count=9,
            section_count=1,
            bullet_count=0,
            duplicate_sentence_count=0,
            duplicate_ratio=0.0,
            answer_too_short=False,
            answer_too_repetitive=False,
            depth_limited_by_evidence=False,
            expanded_by_quality_gate=False,
            deduped_by_repetition_guard=False,
            recommendation_duplicate_shop_count=0,
            final_answer_char_count=9,
            delta_count=0,
            evidence_coverage=1.0,
            forbidden_facet_leak=False,
            unsupported_realtime_claim=False,
        )
        def _final_answer_safety(**kwargs):
            return _FakeSafetyResult(
                answer_text=kwargs["answer_text"],
                final_answer_audit={"passed": True},
                answer_lint={"passed": True, "issues": []},
            )

        with patch("learning_agent_service.local_life.response_builder.bundle.AnswerQualityGate.finalize", return_value=quality_result), patch(
            "learning_agent_service.local_life.response_builder.bundle.apply_final_answer_safety",
            side_effect=_final_answer_safety,
        ):
            result = build_response_bundle(
                raw_query="海底捞水晶城店怎么样？",
                slots=LocalLifeSlots(),
                ranked_candidates=[candidate],
                evidence_claims=[],
                page="assistant",
                current_topic="海底捞水晶城店",
                selected_shop_id=1,
                model_hint={"answer_text": "模型原文"},
            )

        self.assertEqual(result.answer_text.count("模型原文"), 1)
        self.assertTrue(result.answer_text.startswith("模型原文"))
        self.assertTrue(result.metrics.get("llm_primary_output"))
        self.assertFalse(result.metrics.get("template_fallback_used"))
        self.assertFalse(result.metrics.get("contract_block_fallback"))
        self.assertIn("质量门修正后的回答", result.answer_text)

    def test_build_response_bundle_prefers_model_answer_over_template_fallback(self) -> None:
        quality_result = _FakeQualityResult(
            final_answer="LLM 增强回答",
            answer_style="single_shop_review",
            answer_depth_level="normal",
            answer_min_sections=1,
            answer_min_chars=10,
            clean_evidence_count=0,
            strong_evidence_count=0,
            medium_evidence_count=0,
            answer_char_count=8,
            section_count=1,
            bullet_count=0,
            duplicate_sentence_count=0,
            duplicate_ratio=0.0,
            answer_too_short=False,
            answer_too_repetitive=False,
            depth_limited_by_evidence=False,
            expanded_by_quality_gate=False,
            deduped_by_repetition_guard=False,
            recommendation_duplicate_shop_count=0,
            final_answer_char_count=8,
            delta_count=0,
            evidence_coverage=0.0,
            forbidden_facet_leak=False,
            unsupported_realtime_claim=False,
        )

        def _final_answer_safety(**kwargs):
            return _FakeSafetyResult(
                answer_text=kwargs["answer_text"],
                final_answer_audit={"passed": True},
                answer_lint={"passed": True, "issues": []},
            )

        with patch("learning_agent_service.local_life.response_builder.bundle.AnswerQualityGate.finalize", return_value=quality_result), patch(
            "learning_agent_service.local_life.response_builder.bundle.apply_final_answer_safety",
            side_effect=_final_answer_safety,
        ):
            result = build_response_bundle(
                raw_query="娴峰簳鎹炴按鏅跺煄搴楁€庝箞鏍凤紵",
                slots=LocalLifeSlots(),
                ranked_candidates=[],
                evidence_claims=[],
                page="assistant",
                current_topic="娴峰簳鎹炴按鏅跺煄搴?",
                selected_shop_id=1,
                model_hint={"answer_text": "LLM 增强回答"},
            )

        self.assertEqual(result.answer_text, "LLM 增强回答")
        self.assertTrue(result.metrics.get("llm_primary_output"))
        self.assertFalse(result.metrics.get("template_fallback_used"))
        self.assertFalse(result.metrics.get("contract_block_fallback"))

    def test_build_response_bundle_marks_template_fallback_when_no_model_answer(self) -> None:
        quality_result = _FakeQualityResult(
            final_answer="模板兜底回答",
            answer_style="single_shop_review",
            answer_depth_level="normal",
            answer_min_sections=1,
            answer_min_chars=10,
            clean_evidence_count=0,
            strong_evidence_count=0,
            medium_evidence_count=0,
            answer_char_count=6,
            section_count=1,
            bullet_count=0,
            duplicate_sentence_count=0,
            duplicate_ratio=0.0,
            answer_too_short=False,
            answer_too_repetitive=False,
            depth_limited_by_evidence=False,
            expanded_by_quality_gate=False,
            deduped_by_repetition_guard=False,
            recommendation_duplicate_shop_count=0,
            final_answer_char_count=6,
            delta_count=0,
            evidence_coverage=0.0,
            forbidden_facet_leak=False,
            unsupported_realtime_claim=False,
        )

        def _final_answer_safety(**kwargs):
            return _FakeSafetyResult(
                answer_text=kwargs["answer_text"],
                final_answer_audit={"passed": True},
                answer_lint={"passed": True, "issues": []},
            )

        with patch("learning_agent_service.local_life.response_builder.bundle.AnswerQualityGate.finalize", return_value=quality_result), patch(
            "learning_agent_service.local_life.response_builder.bundle.apply_final_answer_safety",
            side_effect=_final_answer_safety,
        ):
            result = build_response_bundle(
                raw_query="这家店怎么样",
                slots=LocalLifeSlots(),
                ranked_candidates=[
                    _FakeCandidate(
                        shop_id=3,
                        name="示例门店",
                        shop_name="示例门店",
                        structured_features={"score": 4.5, "avg_price": 88, "distance_km": 1.1},
                        evidence_features={},
                        vouchers=[],
                        explainable_reasons=["口味稳定"],
                        matched_requirements=[],
                    )
                ],
                evidence_claims=[],
                page="assistant",
                current_topic="示例门店",
                selected_shop_id=3,
                model_hint={},
            )

        self.assertFalse(result.metrics.get("llm_primary_output"))
        self.assertTrue(result.metrics.get("template_fallback_used"))
        self.assertFalse(result.metrics.get("contract_block_fallback"))

    def test_response_builder_exports_still_call_public_helpers(self) -> None:
        candidate = _FakeCandidate(
            shop_id=7,
            name="呷哺呷哺(万达广场店)",
            shop_name="呷哺呷哺(万达广场店)",
            structured_features={"score": 4.2, "avg_price": 80, "distance_km": 2.4},
            evidence_features={},
            vouchers=[],
            explainable_reasons=["口味稳定"],
            matched_requirements=[],
        )

        single_answer = build_single_shop_review_answer("呷哺呷哺(万达广场店)", [candidate], [])
        multi_answer = build_multi_shop_recommendation_answer("附近餐厅", [candidate], [])

        self.assertIn("评分", single_answer)
        self.assertIn("推荐", multi_answer)


if __name__ == "__main__":
    unittest.main()
