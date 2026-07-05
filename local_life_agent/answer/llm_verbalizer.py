from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from ..config import MAX_REWRITE_ATTEMPTS
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
        "{{SEMANTIC_FRAME}}": json.dumps(plan.semantic_frame, ensure_ascii=False),
        "{{SEMANTIC_PARSE_SOURCE}}": plan.semantic_parse_source,
        "{{GROUNDING_STATUS}}": plan.grounding_status,
        "{{MISSING_SLOT_TYPE}}": plan.missing_slot_type,
        "{{ROUTER_POLICY_DECISION}}": json.dumps(plan.router_policy_decision, ensure_ascii=False),
        "{{ROUTER_POLICY_CONFLICTS}}": json.dumps(plan.router_policy_conflicts, ensure_ascii=False),
        "{{EXPLORATION_STAGES}}": json.dumps(plan.exploration_stages, ensure_ascii=False),
        "{{STAGE_QUERIES}}": json.dumps(plan.stage_queries, ensure_ascii=False),
        "{{STAGE_EVIDENCE_REQUIREMENTS}}": json.dumps(plan.stage_evidence_requirements, ensure_ascii=False),
        "{{STAGE_STATUSES}}": json.dumps(plan.stage_statuses, ensure_ascii=False),
        "{{SCENE}}": plan.scene,
        "{{TIME}}": plan.time,
        "{{LOCATION}}": json.dumps(plan.location, ensure_ascii=False),
        "{{FACET_STATUSES}}": json.dumps(getattr(plan, "facet_statuses", {}) or {}, ensure_ascii=False),
        "{{GROUNDED_FACTS}}": json.dumps(getattr(plan, "grounded_facts", {}) or {}, ensure_ascii=False),
        "{{FACET_REASONS}}": json.dumps(getattr(plan, "facet_reasons", {}) or {}, ensure_ascii=False),
        "{{EVIDENCE_STATUS}}": plan.evidence_status,
        "{{COMPARISON_SUPPORT_STATUS}}": plan.comparison_support_status,
        "{{RANKING_PRESERVED}}": json.dumps(plan.ranking_preserved, ensure_ascii=False),
        "{{UNSUPPORTED_REASONS}}": json.dumps(plan.unsupported_reasons, ensure_ascii=False),
        "{{UNKNOWN_FIELDS}}": json.dumps(plan.unknown_fields, ensure_ascii=False),
        "{{FAILED_TOOLS}}": json.dumps(plan.failed_tools, ensure_ascii=False),
        "{{PARTIAL_FIELDS}}": json.dumps(plan.partial_fields, ensure_ascii=False),
        "{{EVIDENCE_REVIEW_RESULT}}": json.dumps(plan.evidence_review_result, ensure_ascii=False),
        "{{ANSWER_VERIFY_RESULT}}": json.dumps(plan.answer_verify_result, ensure_ascii=False),
    }

    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)

    facet_contract_block = "\n".join(
        [
            "### FACET_STATUSES",
            json.dumps(getattr(plan, "facet_statuses", {}) or {}, ensure_ascii=False),
            "### GROUNDED_FACTS",
            json.dumps(getattr(plan, "grounded_facts", {}) or {}, ensure_ascii=False),
            "### FACET_REASONS",
            json.dumps(getattr(plan, "facet_reasons", {}) or {}, ensure_ascii=False),
        ]
    )
    prompt = f"{facet_contract_block}\n\n{prompt}"

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
            "- 对于 grounded_facts 里已经确认的事实，rewrite 必须保留并准确表达，不能把它们降级成 unknown。\n"
            "- 只允许对 facet_statuses 中标记为 unknown / failed / partial 的字段使用保守表达，且只针对对应字段，不要把其他已知事实一起降级。\n"
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

    if not plan.ranking_preserved:
        ranking_markers = ["更好", "最推荐", "胜出", "领先", "综合来看", "整体来看", "更适合", "更近", "更便宜"]
        if any(phrase in text for phrase in ranking_markers):
            return False

    stage_statuses = [str(item).strip().lower() for item in (plan.stage_statuses or []) if str(item).strip()]
    if any(status in {"unknown", "failed", "empty", "partial"} for status in stage_statuses):
        if any(phrase in text for phrase in ["已经安排好", "完整", "全部", "都已", "没有问题", "已成功", "可直接"]):
            return False
        if not any(phrase in text for phrase in ["暂时无法确认", "无法确认", "部分信息", "部分阶段", "还需要补充", "暂时没查到"]):
            return False

    if plan.comparison_support_status and plan.comparison_support_status not in {"grounded", "supported", "ok", "sufficient"}:
        if any(phrase in text for phrase in ["最推荐", "更好", "胜出", "领先", "整体来看", "综合来看", "更适合"]):
            return False

    return True


def _rule_based_verbalize(plan: DecisionPlan) -> str:
    """Build a conservative local fallback answer from the decision plan."""
    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(getattr(plan, "__dict__", {}) or {})
    answer_type = str(plan_dict.get("answer_type", "") or "general")
    selected_targets = list(plan_dict.get("selected_targets") or [])
    main_recommendation_value = plan_dict.get("main_recommendation")
    main_recommendation = (
        main_recommendation_value.model_dump()
        if hasattr(main_recommendation_value, "model_dump")
        else dict(getattr(main_recommendation_value, "__dict__", {}) or {})
    )
    factual_points = [str(item) for item in (plan_dict.get("factual_points") or []) if str(item).strip()]
    uncertainty_notes = [str(item) for item in (plan_dict.get("uncertainty_notes") or []) if str(item).strip()]
    facet_statuses = dict(plan_dict.get("facet_statuses") or {})
    grounded_facts = dict(plan_dict.get("grounded_facts") or {})
    facet_reasons = dict(plan_dict.get("facet_reasons") or {})

    def _target_name() -> str:
        for item in (main_recommendation, *(selected_targets or [])):
            item_dict = item.model_dump() if hasattr(item, "model_dump") else dict(getattr(item, "__dict__", {}) or {})
            name = str(item_dict.get("shop_name", "") or item_dict.get("alias", "") or "").strip()
            if name:
                return name
        return "这家店"

    target_name = _target_name()

    if answer_type in {"single_shop", "single_shop_query"}:
        snippets: list[str] = []
        open_status = str(grounded_facts.get("open_status") or "").lower()
        if open_status == "open":
            snippets.append("目前营业中")
        elif open_status == "closed":
            snippets.append("目前已打烊")
        coupon_count = grounded_facts.get("coupon_count")
        coupon_titles = [str(item).strip() for item in (grounded_facts.get("coupon_titles") or []) if str(item).strip()]
        if coupon_count is not None or coupon_titles:
            if coupon_titles:
                snippets.append(f"当前查到 {len(coupon_titles)} 张优惠券")
            elif int(coupon_count or 0) > 0:
                snippets.append(f"当前查到 {coupon_count} 张优惠券")
            else:
                snippets.append("当前暂无可用优惠券")
        distance_km = grounded_facts.get("distance_km")
        if distance_km is not None:
            dist_snippet = f"距离约 {distance_km} 公里"
            eta_minutes = grounded_facts.get("eta_minutes")
            if eta_minutes is not None:
                dist_snippet += f"，预计 {eta_minutes} 分钟"
            snippets.append(dist_snippet)
        if snippets:
            uncertain_facets = []
            for facet, status in facet_statuses.items():
                if status in {"unknown", "failed", "partial"}:
                    if facet == "distance":
                        uncertain_facets.append("距离信息暂时无法确认")
                    elif facet == "coupon":
                        uncertain_facets.append("优惠情况暂时无法确认")
                    elif facet == "open_status":
                        uncertain_facets.append("营业状态暂时无法确认")
            pieces = [f"{target_name} {'；'.join(snippets)}。"]
            if uncertain_facets:
                pieces.append("".join(dict.fromkeys(uncertain_facets)))
            return " ".join(pieces)
        for point in factual_points:
            if "有券" in point:
                return f"{target_name}{point.split(':', 1)[1].strip() if ':' in point else '有券'}"
        if uncertainty_notes:
            return f"{target_name}暂时无法确认优惠券信息。"
        return f"{target_name}这项信息我已经按当前查询结果整理好了。"

    if answer_type == "comparison":
        names = []
        for item in selected_targets[:2]:
            item_dict = item.model_dump() if hasattr(item, "model_dump") else dict(getattr(item, "__dict__", {}) or {})
            name = str(item_dict.get("shop_name", "") or item_dict.get("alias", "") or "").strip()
            if name:
                names.append(name)
        if len(names) >= 2 and not uncertainty_notes:
            return f"综合当前已知信息，我会优先看{names[0]}，其次是{names[1]}。"
        if len(names) >= 2:
            return f"这两家目前信息还不够完整，我暂时无法确认谁更好，先参考{names[0]}和{names[1]}的已知信息。"
        if names:
            if uncertainty_notes:
                return f"{names[0]}目前信息还不够完整，我暂时无法确认它是不是更好的选择。"
            return f"综合当前已知信息，我会优先看{names[0]}。"
        if uncertainty_notes:
            return "当前已知信息还不够完整，我暂时无法确认哪家更好。"
        return "综合当前已知信息，我会优先参考这些店铺。"

    if answer_type == "recommendation":
        names = []
        for item in selected_targets[:3]:
            item_dict = item.model_dump() if hasattr(item, "model_dump") else dict(getattr(item, "__dict__", {}) or {})
            name = str(item_dict.get("shop_name", "") or item_dict.get("alias", "") or "").strip()
            if name:
                names.append(name)
        if names:
            return f"附近这几家更值得优先看：{'、'.join(names)}。"
        return "我会优先参考当前结果来给你推荐。"

    if answer_type in {"exploration_plan", "exploration"}:
        stage_statuses = [str(item).strip().lower() for item in (plan_dict.get("stage_statuses") or []) if str(item).strip()]
        stage_queries = [str(item).strip() for item in (plan_dict.get("stage_queries") or []) if str(item).strip()]
        segments: list[str] = []
        if stage_queries:
            segments.append("我先按阶段帮你拆开：")
            segments.append(" → ".join(stage_queries))
        else:
            segments.append("我先按阶段帮你拆开这次安排。")
        if any(status in {"unknown", "failed", "empty", "partial"} for status in stage_statuses):
            segments.append("其中有些阶段的信息还不完整，暂时只能给你部分规划。")
        elif uncertainty_notes:
            segments.append("其中有些信息还需要再确认。")
        return " ".join(segments)

    if factual_points:
        return factual_points[0]
    return "我会优先参考当前结果来回答。"


def _invoke_verbalizer_llm(
    llm_client: Any,
    *,
    prompt: str,
    system_prompt: str,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    validator = VerbalizerResponse.model_validate

    def _normalize(result: Any) -> dict[str, Any]:
        """Normalize an LLM result to a dict with 'ok' and 'content'."""
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            # Try to parse JSON string response
            import json
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return {"ok": True, "content": validator(parsed)}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            return {"ok": False, "error_message": "llm_response_not_parsed"}
        return {"ok": False, "error_message": "llm_response_not_dict"}

    if callable(llm_client):
        try:
            result = llm_client(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_ms=timeout_ms,
                response_validator=validator,
            )
            return _normalize(result)
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
            return _normalize(result)

    call_fn = getattr(llm_client, "call_llm", getattr(llm_client, "call", None))
    if not call_fn:
        raise AttributeError("llm_call_missing_callable")
    result = call_fn(
        prompt=prompt,
        system_prompt=system_prompt,
        timeout_ms=timeout_ms,
        response_validator=validator,
    )
    return _normalize(result)


def _mark_template_fallback_metadata(
    metadata_out: dict[str, Any],
    *,
    error_message: str,
    rewrite_count: int,
) -> None:
    metadata_out["answer_source"] = "template_fallback"
    metadata_out["llm_verbalizer_error"] = error_message
    metadata_out["answer_fallback_reason"] = error_message
    metadata_out["answer_verify_passed"] = False
    metadata_out["answer_verify_violations"] = ["template_fallback"]
    metadata_out["rewrite_needed"] = False
    metadata_out["rewrite_count"] = rewrite_count
    metadata_out["final_safety_status"] = "fallback"
    metadata_out["verifier_result"] = "fallback"
    metadata_out["verifier_failure_code"] = "template_fallback"


def verbalize_decision_plan(
    plan: DecisionPlan,
    *,
    llm_client: Any | None = None,
    metadata_out: dict | None = None,
    timeout_ms: int = 30000,
    rewrite_count: int = 0,
    previous_violations: list[str] | None = None,
    in_graph: bool = False,
) -> str:
    """Verbalize a DecisionPlan into natural language via LLM.

    No template fallback — on error, returns a descriptive error message.
    """
    # Check client
    if not llm_client:
        if metadata_out is not None:
            _mark_template_fallback_metadata(
                metadata_out,
                error_message="llm_client_unavailable",
                rewrite_count=rewrite_count,
            )
        return _rule_based_verbalize(plan)

    try:
        system_prompt, _ = _load_verbalizer_prompts()
    except (FileNotFoundError, ValueError, OSError) as exc:
        if metadata_out is not None:
            _mark_template_fallback_metadata(
                metadata_out,
                error_message=str(exc),
                rewrite_count=rewrite_count,
            )
        return _rule_based_verbalize(plan)

    user_prompt = _render_user_prompt(plan, rewrite_count=rewrite_count, previous_violations=previous_violations)
    facet_prefix = "\n".join(
        [
            "### FACET_STATUSES",
            json.dumps(getattr(plan, "facet_statuses", {}) or {}, ensure_ascii=False),
            "### GROUNDED_FACTS",
            json.dumps(getattr(plan, "grounded_facts", {}) or {}, ensure_ascii=False),
            "### FACET_REASONS",
            json.dumps(getattr(plan, "facet_reasons", {}) or {}, ensure_ascii=False),
        ]
    )
    if "FACET_STATUSES" not in user_prompt:
        user_prompt = f"{facet_prefix}\n\n{user_prompt}"

    try:
        res = _invoke_verbalizer_llm(
            llm_client,
            prompt=user_prompt,
            system_prompt=system_prompt,
            timeout_ms=timeout_ms,
        )
    except AttributeError:
        raise RuntimeError("llm_call_missing_callable")
    except Exception as exc:
        if metadata_out is not None:
            _mark_template_fallback_metadata(
                metadata_out,
                error_message=str(exc),
                rewrite_count=rewrite_count,
            )
        return _rule_based_verbalize(plan)

    if not res or not res.get("ok"):
        error_msg = str((res or {}).get("error_message", "") or (res or {}).get("error_code", "") or "llm_call_failed")
        if metadata_out is not None:
            _mark_template_fallback_metadata(
                metadata_out,
                error_message=error_msg,
                rewrite_count=rewrite_count,
            )
        return _rule_based_verbalize(plan)

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
    verifier = B2MiniVerifier(llm_client=llm_client)
    verification_result = verifier.verify(plan, natural_text, timeout_ms=timeout_ms)
    if metadata_out is not None:
        metadata_out["verifier_result"] = "pass" if verification_result["passed"] else "fail"
        metadata_out["verifier_failure_code"] = verification_result.get("failure_code") or verification_result.get("violation") or ""
        metadata_out["verifier_unknown_fields"] = verification_result.get("unknown_fields") or []
        metadata_out["verifier_unsupported_claims"] = verification_result.get("unsupported_claims") or []
        metadata_out["verifier_false_fields"] = verification_result.get("false_fields") or []
        metadata_out["verifier_recoverable"] = bool(verification_result.get("recoverable", False))
    if not verification_result["passed"]:
        if metadata_out is not None:
            violations = verification_result.get("violations") or [str(verification_result.get("violation", ""))]
            metadata_out["violation"] = verification_result["violation"]
            metadata_out["violations"] = violations
            metadata_out["llm_verbalizer_error"] = violations
            metadata_out["answer_verify_passed"] = False
            metadata_out["answer_verify_violations"] = violations
            metadata_out["rewrite_needed"] = in_graph and rewrite_count < _GRAPH_REWRITE_LIMIT and bool(verification_result.get("recoverable", False))
            metadata_out["rewrite_count"] = rewrite_count
            metadata_out["rewrite_reason"] = verification_result["violation"]
            metadata_out["final_safety_status"] = "violated"

        # If in graph and rewrite is still under limit, return natural_text to let verifier fail & trigger rewrite
        if in_graph and rewrite_count < _GRAPH_REWRITE_LIMIT and bool(verification_result.get("recoverable", False)):
            return natural_text
        # Verification failed and no rewrite available — return natural_text + note
        error_note = f"\n\n【注意】LLM 回答未通过可信性校验，可能存在不准确信息。"
        return natural_text + error_note

    if metadata_out is not None:
        metadata_out["answer_verify_passed"] = True
        metadata_out["answer_verify_violations"] = []
        metadata_out["rewrite_needed"] = False
        metadata_out["rewrite_count"] = rewrite_count
        metadata_out["rewrite_reason"] = ""
        metadata_out["final_safety_status"] = "safe"

    return natural_text


