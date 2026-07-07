from __future__ import annotations

from ..answer.verifier import verify_answer


def test_empty_evidence_and_draft_never_pass():
    report = verify_answer("", {}, "single_shop")
    assert report["passed"] is False
    assert report["failure_code"] == "empty_evidence_or_draft"


def test_empty_evidence_never_passes():
    report = verify_answer("川味轩目前营业中。", {}, "single_shop")
    assert report["passed"] is False
    assert report["failure_code"] == "empty_evidence_or_draft"


def test_empty_draft_never_passes():
    report = verify_answer("", {"evidence_items": [{"facet": "open_status", "value": "open"}]}, "single_shop")
    assert report["passed"] is False
    assert report["failure_code"] == "empty_evidence_or_draft"
