from __future__ import annotations

from pathlib import Path

from ..semantic.slot_extractor import extract_slots


def test_slot_extractor_does_not_import_mock_tools():
    source = Path(__file__).resolve().parent.parent / "semantic" / "slot_extractor.py"
    text = source.read_text(encoding="utf-8")

    assert "from ..tools.mock_tools import _all_shops" not in text


def test_slot_extractor_fallback_still_recognises_mock_shop_names():
    result = extract_slots("海底捞有券吗", "local_life")

    assert result["merchant_mentions"]
    assert "海底捞" in result["merchant_mentions"][0]


def test_llm_success_path_does_not_need_fallback_shop_token():
    result = extract_slots("这三家哪个好", "local_life")

    assert result["task_type"].value == "comparison"
    assert result["merchant_mentions"] == []
