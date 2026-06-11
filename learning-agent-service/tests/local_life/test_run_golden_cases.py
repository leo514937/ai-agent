import json

from learning_agent_service.local_life.eval.run_golden_cases import GoldenCase, load_golden_cases


def test_golden_case_from_new_format_mapping():
    raw = {
        "case_id": "N1",
        "intent": "comparison",
        "description": "新格式 case",
        "turns": [{"user": "海底捞和巴奴哪个好"}],
        "expected_output_contains": ["海底捞", "巴奴"],
        "forbidden_output": ["推荐其他店"],
        "expected_metrics": {"answer_style": "comparison"},
    }

    case = GoldenCase.from_mapping(raw)

    assert case.case_id == "N1"
    assert case.intent == "comparison"
    assert case.turns == ("海底捞和巴奴哪个好",)
    assert case.expected_contains == ("海底捞", "巴奴")
    assert case.expected_not_contains == ("推荐其他店",)


def test_load_golden_cases_supports_new_format_turn_objects(tmp_path):
    path = tmp_path / "cases.jsonl"
    payload = {
        "case_id": "N2",
        "description": "turn object",
        "turns": [{"user": "适合约会的餐厅推荐"}],
        "expected_output_contains": ["约会", "推荐"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    cases = load_golden_cases(path)

    assert len(cases) == 1
    assert cases[0].turns == ("适合约会的餐厅推荐",)
    assert cases[0].expected_contains == ("约会", "推荐")
