"""Answer verifier — checks generated answers against evidence for
factual accuracy and adherence to allowed/disallowed phrasing rules.
Supports rewrite retries when verification fails.
"""

from __future__ import annotations

from typing import Any


def _to_dict(value: Any) -> dict[str, Any]:
    """Best-effort conversion of evidence objects into a plain dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _extract_ranked_shop_names(evidence: dict[str, Any]) -> list[str]:
    """Extract the expected shop order from a ranking snapshot."""
    snapshot = evidence.get("ranking_snapshot") or {}
    ranked = snapshot.get("ranked") or snapshot.get("ranked_shops") or snapshot.get("shops") or []
    shop_names: list[str] = []
    for item in ranked:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = (
                item.get("shop_name")
                or item.get("name")
                or item.get("shop_id")
                or ""
            )
            if isinstance(name, str):
                name = name.strip()
        else:
            name = str(item).strip()
        if name:
            shop_names.append(name)
    return shop_names


def _extract_mentioned_order(answer: str, expected_names: list[str]) -> list[str]:
    """Return expected shop names in the order they appear in the answer."""
    mentions: list[tuple[int, str]] = []
    for name in expected_names:
        idx = answer.find(name)
        if idx >= 0:
            mentions.append((idx, name))
    mentions.sort(key=lambda item: item[0])
    return [name for _, name in mentions]


def _build_suggested_fix(issues: list[str]) -> str:
    """Generate a compact fix hint from the detected issues."""
    parts: list[str] = []
    if any(issue == "ranking_changed_by_llm" for issue in issues):
        parts.append("请严格按 evidence.ranking_snapshot 的顺序输出，不要重排候选店。")
    if any(issue.startswith("forbidden_claim:") for issue in issues):
        parts.append("删除未被 evidence 支持的断言，只保留可验证事实。")
    if not parts:
        parts.append("请仅输出 evidence 支持的内容。")
    return "".join(parts)


def verify_answer(answer: str, evidence: dict, task_type: str) -> dict:
    """Verify an answer against its evidence base.

    Args:
        answer: Generated answer text.
        evidence: Evidence pack with confirmed facts.
        task_type: Task type for context-specific rules.

    Returns:
        {"passed": True} or
        {"passed": False, "issues": [...], "suggested_fix": "..."}.
    """
    evidence_dict = _to_dict(evidence)
    issues: list[str] = []

    forbidden_claims = evidence_dict.get("forbidden_claims") or []
    for claim in forbidden_claims:
        if isinstance(claim, str) and claim and claim in answer:
            issues.append(f"forbidden_claim:{claim}")

    expected_names = _extract_ranked_shop_names(evidence_dict)
    if len(expected_names) >= 2:
        mentioned_order = _extract_mentioned_order(answer, expected_names)
        if len(mentioned_order) >= 2:
            expected_order = [name for name in expected_names if name in mentioned_order]
            if mentioned_order != expected_order:
                issues.append("ranking_changed_by_llm")

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "suggested_fix": "" if passed else _build_suggested_fix(issues),
        "task_type": task_type,
    }
