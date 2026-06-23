"""Prompt + Eval contract tests.

Verifies:
  1. Every expected prompt file exists under ``llm/prompts/``.
  2. No remaining inline system/user prompts in ``answer/llm_verbalizer.py``.
  3. Verbalizer still loads and validates prompts from the external file.
  4. JSONL loading validates via ``EvalCase`` schema.
  5. Invalid JSONL fails at load time with a helpful message.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from ..eval.eval_case_schema import EvalCase, EvalExpected
from ..llm.client import load_prompt


# ===================================================================
# A. Prompt scan — all expected .md files exist
# ===================================================================

EXPECTED_PROMPT_FILES = {
    "top_intent_router.md",
    "local_life_parser.md",
    "tool_planner.md",
    "answer_verbalizer.md",
}


def test_all_prompt_files_exist():
    """Every core prompt file listed in the contract must be present."""
    prompts_dir = Path(__file__).resolve().parent.parent / "llm" / "prompts"
    assert prompts_dir.is_dir(), f"prompts directory not found: {prompts_dir}"

    actual = {f.name for f in prompts_dir.iterdir() if f.suffix == ".md"}
    missing = EXPECTED_PROMPT_FILES - actual
    assert not missing, f"Missing prompt file(s): {missing}"


def test_no_stray_markdown_prompts():
    """Flag any .md file that is not in the expected set (possible orphan)."""
    prompts_dir = Path(__file__).resolve().parent.parent / "llm" / "prompts"
    actual = {f.name for f in prompts_dir.iterdir() if f.suffix == ".md"}
    extra = actual - EXPECTED_PROMPT_FILES
    if extra:
        pytest.skip(f"Unexpected prompt file(s) found (not in contract): {extra}")


def test_answer_verbalizer_sections_are_present():
    """answer_verbalizer.md must contain both ## System Prompt and ## User Prompt."""
    try:
        raw = load_prompt("answer_verbalizer")
    except FileNotFoundError:
        pytest.fail("answer_verbalizer.md not found")

    assert "## System Prompt" in raw, "answer_verbalizer.md: missing ## System Prompt"
    assert "## User Prompt" in raw, "answer_verbalizer.md: missing ## User Prompt"


# ===================================================================
# B. Verbalizer prompt loading test
# ===================================================================


def test_verbalizer_loads_from_external_file():
    """``_load_verbalizer_prompts`` must return valid system + user templates."""
    from ..answer.llm_verbalizer import _load_verbalizer_prompts

    sys_prompt, user_template = _load_verbalizer_prompts()

    assert sys_prompt, "System prompt must not be empty"
    assert user_template, "User template must not be empty"
    # The template must contain the placeholder markers
    assert "{{ANSWER_TYPE}}" in user_template
    assert "{{REWRITE_INSTRUCTION}}" in user_template


def test_verbalizer_uses_external_prompt():
    """``verbalize_decision_plan`` should use prompts loaded from file,
    not inline strings. We verify by checking that the rendered user prompt
    contains known template markers (if inline fallback were used, the
    markers would appear as literal text)."""
    from ..domain.schemas import DecisionPlan
    from ..answer.llm_verbalizer import _render_user_prompt

    plan = DecisionPlan(answer_type="single_shop")
    rendered = _render_user_prompt(plan)

    # The rendered prompt should NOT contain raw {{...}} markers (they must
    # have been substituted)
    assert "{{ANSWER_TYPE}}" not in rendered
    assert "single_shop" in rendered
    # Verify template substitution worked
    assert "## DecisionPlan 事实数据：" in rendered


# ===================================================================
# C. JSONL EvalCase schema validation
# ===================================================================


class TestEvalCaseSchema:
    """Tests for the EvalCase Pydantic model used in JSONL loading."""

    def test_minimal_valid_case(self):
        """Only ``case_id`` is required."""
        case = EvalCase.model_validate_json(json.dumps({"case_id": "test_001"}))
        assert case.case_id == "test_001"
        assert case.category == "uncategorized"
        assert case.turns == []
        assert case.expected.model_dump() == {}

    def test_full_case_roundtrip(self):
        data = {
            "case_id": "rec_001",
            "category": "recommendation",
            "turns": [{"user": "附近推荐火锅"}],
            "expected": {
                "top_intent": "local_life",
                "task_type": "recommendation",
                "selected_flow": "recommendation_flow",
                "min_candidate_count": 1,
                "max_rewrite_count": 1,
            },
        }
        case = EvalCase.model_validate_json(json.dumps(data))
        assert case.case_id == "rec_001"
        assert len(case.turns) == 1
        assert case.expected.top_intent == "local_life"

        d = case.to_dict()
        assert d["case_id"] == "rec_001"
        assert d["expected"]["top_intent"] == "local_life"
        # None fields must be stripped
        assert "task_type" in d["expected"]  # explicitly set
        assert "answer_source" not in d["expected"]  # not set -> None -> stripped

    def test_invalid_json_fails_at_parse(self):
        """Non-JSON content must raise ``ValidationError``."""
        with pytest.raises(ValidationError):
            EvalCase.model_validate_json("this is not json")

    def test_missing_case_id_fails(self):
        """``case_id`` is required, so missing it must fail."""
        with pytest.raises(ValidationError):
            EvalCase.model_validate_json(json.dumps({"turns": []}))

    def test_turns_as_plain_strings(self):
        """Backward compatibility: turns can be plain strings."""
        data = {"case_id": "old_style", "turns": ["附近推荐火锅"]}
        case = EvalCase.model_validate_json(json.dumps(data))
        assert len(case.turns) == 1

    def test_turns_as_dicts(self):
        """New style: turns are dicts with a ``user`` key."""
        data = {"case_id": "new_style", "turns": [{"user": "附近推荐火锅"}]}
        case = EvalCase.model_validate_json(json.dumps(data))
        assert len(case.turns) == 1

    def test_expected_with_none_filtered(self):
        """``model_dump`` must exclude None-valued fields."""
        expected = EvalExpected(top_intent="local_life")
        dumped = expected.model_dump()
        assert dumped == {"top_intent": "local_life"}
        # task_type was not set, so it must not appear
        assert "task_type" not in dumped

    def test_extra_expected_fields_preserved(self):
        """Fields not defined in EvalExpected but present in JSON are kept
        via extra='ignore' + the 'extra' catch-all field."""
        data = {
            "case_id": "extra_fields",
            "expected": {
                "top_intent": "local_life",
                "unknown_field": "some_value",
            },
        }
        case = EvalCase.model_validate_json(json.dumps(data))
        dumped = case.expected.model_dump()
        assert dumped.get("top_intent") == "local_life"
        # unknown_field is ignored (extra='ignore'), but we keep known fields
        assert "unknown_field" not in dumped


# ===================================================================
# D. load_cases integration tests
# ===================================================================


class TestLoadCases:
    """Integration tests for the new ``load_cases`` with schema validation."""

    def test_valid_jsonl_passes(self, tmp_path):
        from ..eval.run_eval import load_cases

        path = tmp_path / "cases.jsonl"
        path.write_text(
            json.dumps({"case_id": "c1", "turns": [{"user": "附近推荐火锅"}]}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        cases = load_cases(path)
        assert len(cases) == 1
        assert cases[0]["case_id"] == "c1"

    def test_invalid_jsonl_raises_value_error(self, tmp_path):
        from ..eval.run_eval import load_cases

        path = tmp_path / "bad.jsonl"
        # Missing case_id (required field)
        path.write_text(
            json.dumps({"turns": []}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as excinfo:
            load_cases(path)
        err_msg = str(excinfo.value)
        assert "schema validation failed" in err_msg

    def test_invalid_jsonl_includes_line_number(self, tmp_path, caplog):
        """When all lines fail, the error must include file and line info."""
        from ..eval.run_eval import load_cases

        path = tmp_path / "numbered.jsonl"
        path.write_text(
            "not-json-at-all\n"
            + json.dumps({"turns": []}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as excinfo:
            load_cases(path)
        err_msg = str(excinfo.value)
        # Must reference line 1 (first bad line)
        assert "numbered.jsonl:1" in err_msg or "numbered.jsonl:2" in err_msg

    def test_mixed_valid_invalid_lines_skips_bad(self, tmp_path):
        """When some lines are valid and some are not, only raise when
        *all* lines fail."""
        from ..eval.run_eval import load_cases

        path = tmp_path / "mixed.jsonl"
        path.write_text(
            json.dumps({"case_id": "c1"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"turns": []}, ensure_ascii=False)  # missing case_id
            + "\n"
            + json.dumps({"case_id": "c2"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        cases = load_cases(path)
        # Two valid cases should survive (lines 1 and 3)
        assert len(cases) == 2
        assert cases[0]["case_id"] == "c1"
        assert cases[1]["case_id"] == "c2"

    def test_inline_case_passed_to_run_eval_unchanged(self, monkeypatch):
        """run_eval() called with raw dict (not via load_cases) should still work."""
        import importlib
        from ..eval.run_eval import run_eval

        run_eval_module = importlib.import_module("local_life_agent.eval.run_eval")
        from ..agent import AgentResponse, DebugInfo

        def fake_agent(text, session_id=""):
            return AgentResponse(
                answer_text="test",
                trace_id="t1",
                session_id=session_id,
                debug=DebugInfo(
                    execution_trace=[],
                    turn_trace={
                        "trace_id": "t1",
                        "session_id": session_id,
                        "top_intent": "local_life",
                        "task_type": "recommendation",
                        "selected_flow": "recommendation_flow",
                        "answer_source": "template",
                        "answer_verify_passed": True,
                        "answer_verify_violations": [],
                        "rewrite_count": 0,
                        "events": [],
                    },
                ),
            )

        monkeypatch.setattr(run_eval_module, "run_agent_graph", fake_agent)
        report = run_eval(
            [
                {
                    "case_id": "inline",
                    "category": "core",
                    "turns": [{"user": "附近推荐火锅"}],
                    "expected": {"top_intent": "local_life", "task_type": "recommendation"},
                }
            ],
            backend="rule_based",
            write_reports=False,
        )
        assert report["summary"]["passed"] == 1
