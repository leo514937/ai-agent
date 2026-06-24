from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from ..config import ENABLE_LLM_VERBALIZER, MAX_REWRITE_ATTEMPTS
from ..domain.schemas import DecisionPlan
from ..llm.client import load_prompt


_GRAPH_REWRITE_LIMIT = max(1, MAX_REWRITE_ATTEMPTS - 1)

# ---------------------------------------------------------------------------
# Prompt loading — externalised to llm/prompts/answer_verbalizer.md
# ---------------------------------------------------------------------------

_VERBALIZER_SYSTEM_PROMPT: str | None = None
_VERBALIZER_USER_TEMPLATE: str | None = None


def _load_verbalizer_prompts() -> tuple[str, str]:
    """Load system and user prompt templates from the external markdown file.

    Returns:
        (system_prompt, user_prompt_template)

    Raises:
        FileNotFoundError: if the prompt file does not exist.
        ValueError: if the file content cannot be parsed into two sections.
    """
    global _VERBALIZER_SYSTEM_PROMPT, _VERBALIZER_USER_TEMPLATE
    if _VERBALIZER_SYSTEM_PROMPT is not None and _VERBALIZER_USER_TEMPLATE is not None:
        return _VERBALIZER_SYSTEM_PROMPT, _VERBALIZER_USER_TEMPLATE

    raw = load_prompt("answer_verbalizer")
    # Split on "## User Prompt" — the system section is everything before it
    marker = "## User Prompt"
    if marker not in raw:
        raise ValueError(
            "answer_verbalizer.md: missing '## User Prompt' section delimiter. "
            "Expected format: '# 答案生成 Verbalizer\\n\\n## System Prompt\\n...\\n\\n## User Prompt\\n...'"
        )

    sys_part, user_part = raw.split(marker, 1)
    # Extract system content: skip title and ## System Prompt header
    system_lines: list[str] = []
    for line in sys_part.splitlines():
        stripped = line.strip()
        # Skip title line, ## System Prompt header, and blank lines at the start
        if stripped in ("# 答案生成 Verbalizer", "## System Prompt") or (not system_lines and not stripped):
            continue
        system_lines.append(line)
    system_prompt = "\n".join(system_lines).strip()

    user_prompt_template = user_part.strip()

    if not system_prompt:
        raise ValueError("answer_verbalizer.md: system prompt section is empty")
    if not user_prompt_template:
        raise ValueError("answer_verbalizer.md: user prompt section is empty")

    _VERBALIZER_SYSTEM_PROMPT = system_prompt
    _VERBALIZER_USER_TEMPLATE = user_prompt_template
    return system_prompt, user_prompt_template


def _render_user_prompt(
    plan: DecisionPlan,
    rewrite_count: int = 0,
    previous_violations: list[str] | None = None,
) -> str:
    """Render the user prompt template with DecisionPlan data."""
    _, template = _load_verbalizer_prompts()

    replacements = {
        "{{ANSWER_TYPE}}": plan.answer_type,
        "{{DECISION_CONTEXT}}": json.dumps(plan.decision_context, ensure_ascii=False),
        "{{CONVERSATION_CONTINUITY}}": json.dumps(plan.conversation_continuity, ensure_ascii=False),
        "{{SELECTED_TARGETS}}": json.dumps(plan.selected_targets, ensure_ascii=False),
        "{{OMITTED_TARGETS}}": json.dumps(plan.omitted_targets, ensure_ascii=False),
        "{{CANDIDATE_SUMMARIES}}": json.dumps(plan.candidate_summaries, ensure_ascii=False),
        "{{MAIN_RECOMMENDATION}}": json.dumps(plan.main_recommendation, ensure_ascii=False),
        "{{OVERALL_RANKING}}": json.dumps(plan.overall_ranking, ensure_ascii=False),
        "{{BEST_FOR}}": json.dumps(plan.best_for, ensure_ascii=False),
        "{{FACTUAL_POINTS}}": json.dumps(plan.factual_points, ensure_ascii=False),
        "{{UNCERTAINTY_NOTES}}": json.dumps(plan.uncertainty_notes, ensure_ascii=False),
        "{{MUST_MENTION_UNKNOWNS}}": json.dumps(plan.must_mention_unknowns, ensure_ascii=False),
        "{{FORBIDDEN_CLAIMS}}": json.dumps(plan.forbidden_claims, ensure_ascii=False),
    }

    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)

    # Build rewrite instruction if needed
    if rewrite_count > 0 and previous_violations:
        violations_text = "\n".join(f"- {v}" for v in previous_violations)
        lq = "\u201c"
        rq = "\u201d"
        rewrite_instruction = (
            f"\n\n注意：这已经是第 {rewrite_count} 次重写，你之前的输出未能通过可信性校验。\n"
            f"违反的规则编码：\n{violations_text}\n\n"
            "请遵循以下修改原则：\n"
            f"- 如果 coupon/open_status/distance/price/rating 是 unknown 或工具失败，"
            f"必须表述为{lq}暂时无法确认{rq}、{lq}暂时没查到{rq}等，"
            f"绝不能声称{lq}没有{rq}或编造具体数值。\n"
            "- 只提及 selected_targets 和 omitted_targets 里的店铺，绝不捏造或提及其他店名。\n"
            "- 严格保留整体推荐/对比的排序顺序，不得擅自更改。\n"
            f"- 如果有 omitted_targets 且非空，绝对不能说{lq}对比了全部{rq}、{lq}对比了所有几家{rq}等全量表述。\n"
            "- 纠正属性绑定，不要串店、串券、串距离。\n"
            "请修正并重新输出自然语言回复的 JSON。"
        )
    else:
        rewrite_instruction = ""

    prompt = prompt.replace("{{REWRITE_INSTRUCTION}}", rewrite_instruction)
    return prompt


class VerbalizerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    natural_response: str = Field(description="The natural language response for the user.")


def _load_all_known_shop_names() -> list[str]:
    # Static mock data removed in P1; returns empty
    return []


def _check_boundary(plan: DecisionPlan, text: str) -> bool:
    # 1. LLM 输出不能包含不在 selected_targets + omitted_targets 中的已知 shop_name。
    known_names = _load_all_known_shop_names()
    allowed_names = set()
    for item in plan.selected_targets + plan.omitted_targets:
        if item.get("shop_name"):
            allowed_names.add(str(item["shop_name"]).strip())
            brand_name = str(item["shop_name"]).strip()
            if "(" in brand_name:
                allowed_names.add(brand_name.split("(", 1)[0].strip())
        if item.get("alias"):
            allowed_names.add(str(item["alias"]).strip())

    for name in known_names:
        if name in text:
            is_allowed = False
            for allowed in allowed_names:
                if name in allowed or allowed in name:
                    is_allowed = True
                    break
            if not is_allowed:
                return False

    # 2. LLM 输出不能出现明显 forbidden_claims 里的内容。
    for claim in plan.forbidden_claims:
        if claim in text:
            return False

    # 3. 如果 omitted_targets 非空，LLM 不能说“已对比所有 X 家”。
    if plan.omitted_targets:
        forbidden_phrases = ["对比了所有", "对比了全部", "分析了全部", "分析了所有", "对比了全部几家", "对比了全部店"]
        for phrase in forbidden_phrases:
            if phrase in text:
                return False

    # 4. 如果 uncertainty_notes 非空，LLM 不能把“不确定”表达成确定否定
    if plan.uncertainty_notes:
        certain_negative_phrases = ["没有券", "肯定没券", "一定关门", "明显更差", "肯定打烊", "没有可用券"]
        for phrase in certain_negative_phrases:
            if phrase in text:
                return False

    return True


def _invoke_verbalizer_llm(
    llm_client: Any,
    *,
    prompt: str,
    system_prompt: str,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    validator = VerbalizerResponse.model_validate

    if callable(llm_client):
        try:
            result = llm_client(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=validator,
            )
            return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}
        except TypeError as exc:
            if "response_validator" not in str(exc):
                raise
            from ..llm.client import call_llm
            result = call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=validator,
                backend=llm_client,
            )
            return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}

    call_fn = getattr(llm_client, "call_llm", getattr(llm_client, "call", None))
    if not call_fn:
        raise AttributeError("llm_call_missing_callable")
    result = call_fn(
        prompt=prompt,
        system_prompt=system_prompt,
        timeout_ms=timeout_ms,
        response_validator=validator,
    )
    return result if isinstance(result, dict) else {"ok": False, "error_message": "llm_response_not_dict"}


def verbalize_decision_plan(
    plan: DecisionPlan,
    *,
    llm_client: Any | None = None,
    fallback_text: str = "",
    metadata_out: dict | None = None,
    timeout_ms: int = 30000,
    rewrite_count: int = 0,
    previous_violations: list[str] | None = None,
    in_graph: bool = False,
) -> str:
    # Check client
    if not llm_client:
        raise RuntimeError("llm_client_unavailable")

    try:
        system_prompt, _ = _load_verbalizer_prompts()
    except (FileNotFoundError, ValueError, OSError) as exc:
        if metadata_out is not None:
            metadata_out["answer_fallback_reason"] = "prompt_load_failed"
            metadata_out["llm_verbalizer_error"] = str(exc)
            metadata_out["answer_verify_passed"] = False
            metadata_out["answer_verify_violations"] = ["prompt_load_failed"]
            metadata_out["rewrite_needed"] = False
            metadata_out["rewrite_count"] = rewrite_count
            metadata_out["fallback_reason"] = "prompt_load_failed"
            metadata_out["final_safety_status"] = "fallback"
        raise RuntimeError(f"prompt_load_failed:{exc}") from exc

    user_prompt = _render_user_prompt(plan, rewrite_count=rewrite_count, previous_violations=previous_violations)

    try:
        try:
            res = _invoke_verbalizer_llm(
                llm_client,
                prompt=user_prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
            )
        except AttributeError:
            raise RuntimeError("llm_call_missing_callable")

        if not res or not res.get("ok"):
            raise RuntimeError(str((res or {}).get("error_message", "") or (res or {}).get("error_code", "") or "llm_call_failed"))

        content = res.get("content")
        if isinstance(content, VerbalizerResponse):
            natural_text = content.natural_response
        elif isinstance(content, dict):
            natural_text = content.get("natural_response", "")
        else:
            raise RuntimeError("missing_natural_response")

        if not natural_text:
            raise RuntimeError("empty_natural_response")

        if metadata_out is not None:
            metadata_out["generated_llm_answer_before_fallback"] = natural_text

        from .b2_mini_verifier import B2MiniVerifier
        verifier = B2MiniVerifier()
        verification_result = verifier.verify(plan, natural_text)
        if not verification_result["passed"]:
            if metadata_out is not None:
                metadata_out["violation"] = verification_result["violation"]
                metadata_out["violations"] = verification_result["violations"]
                metadata_out["answer_fallback_reason"] = f"b2_mini_verifier:{verification_result['violation'] or 'unknown'}"
                metadata_out["llm_verbalizer_error"] = verification_result["violations"]
                metadata_out["answer_verify_passed"] = False
                metadata_out["answer_verify_violations"] = verification_result["violations"]
                metadata_out["rewrite_needed"] = in_graph and rewrite_count < _GRAPH_REWRITE_LIMIT
                metadata_out["rewrite_count"] = rewrite_count
                metadata_out["rewrite_reason"] = verification_result["violation"]
                metadata_out["fallback_reason"] = f"b2_mini_verifier:{verification_result['violation'] or 'unknown'}"
                metadata_out["final_safety_status"] = "violated"
            
            # If in graph and rewrite is still under limit, return natural_text to let verifier fail & trigger rewrite
            if in_graph and rewrite_count < _GRAPH_REWRITE_LIMIT:
                return natural_text
            raise RuntimeError(f"b2_mini_verifier:{verification_result['violation'] or 'unknown'}")

        if metadata_out is not None:
            metadata_out["answer_verify_passed"] = True
            metadata_out["answer_verify_violations"] = []
            metadata_out["rewrite_needed"] = False
            metadata_out["rewrite_count"] = rewrite_count
            metadata_out["rewrite_reason"] = ""
            metadata_out["fallback_reason"] = ""
            metadata_out["final_safety_status"] = "safe"

        return natural_text
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


