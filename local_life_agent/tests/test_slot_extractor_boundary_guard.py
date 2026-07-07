from __future__ import annotations

from pathlib import Path

from local_life_agent.semantic.slot_extractor import extract_slots


def test_slot_extractor_keeps_only_anchor_and_candidate_signals():
    result = extract_slots("海底捞(牡丹园店)和巴奴哪个更适合聚餐，要性价比高", "local_life")

    assert result["comparison_intent"] is True
    assert result["merchant_mentions"]
    assert result["comparison_targets"]
    assert result["preference_signals"]
    assert result["shop_target"] is None
    assert "shop_id" not in result
    assert result["workflow_hint"] == "comparison"


def test_slot_extractor_marks_compat_fields_as_deprecated():
    source = Path(__file__).resolve().parent.parent / "semantic" / "slot_extractor.py"
    text = source.read_text(encoding="utf-8")

    assert "DEPRECATED_COMPAT" in text
    assert "graph_builder" not in text

