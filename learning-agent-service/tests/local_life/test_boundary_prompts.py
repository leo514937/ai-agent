"""Tests for boundary prompts."""
from learning_agent_service.local_life.boundary_prompts import (
    get_boundary_prompt,
    get_freshness_prompt,
    BOUNDARY_PROMPTS,
)


def test_get_boundary_prompt_default():
    prompt = get_boundary_prompt("no_location")
    assert "位置" in prompt


def test_get_boundary_prompt_with_shop():
    prompt = get_boundary_prompt("no_coupon_evidence", shop_name="海底捞")
    assert "海底捞" in prompt


def test_get_boundary_prompt_unknown_key():
    prompt = get_boundary_prompt("unknown_key")
    assert "信息" in prompt


def test_get_freshness_prompt_historical():
    prompt = get_freshness_prompt("historical", shop_name="海底捞")
    assert prompt is not None
    assert "过时" in prompt or "最新" in prompt


def test_get_freshness_prompt_realtime():
    prompt = get_freshness_prompt("realtime")
    assert prompt is None


def test_all_prompts_are_strings():
    for key, value in BOUNDARY_PROMPTS.items():
        assert isinstance(value, str), f"Prompt {key} is not a string"