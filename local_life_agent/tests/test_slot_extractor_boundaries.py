from __future__ import annotations

from pathlib import Path

from ..semantic.slot_extractor import extract_slots


def test_slot_extractor_does_not_import_mock_tools():
    source = Path(__file__).resolve().parent.parent / "semantic" / "slot_extractor.py"
    text = source.read_text(encoding="utf-8")

    assert "from ..tools.mock_tools import _all_shops" not in text


def test_slot_extractor_fallback_still_recognises_mock_shop_names():
    result = extract_slots("海底捞火锅(湖滨店)有券吗", "local_life")

    assert result["surface_hints"]
    assert "有券" in result["surface_hints"]
    assert result["alias_hints"]
    assert "海底捞火锅(湖滨店)" in result["alias_hints"] or "海底捞火锅" in result["alias_hints"]


def test_slot_extractor_recognises_eta_style_distance_query():
    result = extract_slots("海底捞水晶城店多久能到？", "local_life")

    assert "distance" in result["focused_facets"]


def test_slot_extractor_marks_service_feature_as_unsupported():
    result = extract_slots("海底捞(牡丹园店)有没有宠物寄存服务？", "local_life")

    assert result["task_type"].value == "single_shop_query"
    assert result["unsupported_facets"] == ["service_feature"]
    assert any(reason.startswith("unsupported_service:") for reason in result["unsupported_reasons"])


def test_slot_extractor_marks_child_seat_as_unsupported():
    result = extract_slots("海底捞(牡丹园店)有没有儿童座椅？", "local_life")

    assert result["task_type"].value == "single_shop_query"
    assert result["unsupported_facets"] == ["service_feature"]
    assert any(reason.startswith("unsupported_service:") for reason in result["unsupported_reasons"])


def test_llm_success_path_does_not_need_fallback_shop_token():
    result = extract_slots("这三家哪个好", "local_life")

    assert result["task_type"].value == "comparison"
    assert result["merchant_mentions"] == []
