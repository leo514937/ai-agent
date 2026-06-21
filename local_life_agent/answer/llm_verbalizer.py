from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from ..config import ENABLE_LLM_VERBALIZER, LLM_VERBALIZER_FALLBACK_TO_TEMPLATE
from ..domain.schemas import DecisionPlan


class VerbalizerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    natural_response: str = Field(description="The natural language response for the user.")


def _load_all_known_shop_names() -> list[str]:
    mock_file = Path(__file__).resolve().parent.parent / "mock_data" / "shops.json"
    if not mock_file.exists():
        return []
    try:
        with open(mock_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            names = []
            for item in data:
                if item.get("shop_name"):
                    names.append(str(item["shop_name"]).strip())
                if item.get("alias"):
                    names.append(str(item["alias"]).strip())
                for a in item.get("aliases", []) or []:
                    names.append(str(a).strip())
            return list(set(names))
    except Exception:
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
) -> dict[str, Any]:
    validator = VerbalizerResponse.model_validate

    if callable(llm_client):
        try:
            return llm_client(
                prompt=prompt,
                system_prompt=system_prompt,
                response_validator=validator,
            )
        except TypeError as exc:
            if "response_validator" not in str(exc):
                raise
            from ..llm.client import call_llm
            return call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                response_validator=validator,
                backend=llm_client,
            )

    call_fn = getattr(llm_client, "call_llm", getattr(llm_client, "call", None))
    if not call_fn:
        raise AttributeError("llm_call_missing_callable")
    return call_fn(
        prompt=prompt,
        system_prompt=system_prompt,
        response_validator=validator,
    )


def verbalize_decision_plan(
    plan: DecisionPlan,
    *,
    llm_client: Any | None = None,
    fallback_text: str = "",
    metadata_out: dict | None = None,
) -> str:
    # Check client
    if not llm_client:
        if metadata_out is not None:
            metadata_out["answer_fallback_reason"] = "llm_client_unavailable"
            metadata_out["llm_verbalizer_error"] = "llm_client_unavailable"
        return fallback_text

    system_prompt = (
        "你是一个本地生活助手（顾问），你需要根据提供给你的 `DecisionPlan` 事实生成一段自然、亲和、流畅的中文回复。\n"
        "你必须严格遵守以下规则：\n"
        "1. 只能陈述 DecisionPlan 中提供的事实（即 selected_targets、factual_points、best_for 里的内容），严禁编造任何 DecisionPlan 中没有提及的距离、时间、评分、优惠金额等信息。\n"
        "2. 对于不确定项或未查到的信息（列在 uncertainty_notes 中），必须表述为“暂时无法确认”、“暂时没查到”或“无法确认”，绝不能编造肯定语气或声称没有该信息（如不要说“没有券”或“已经关门”，而要说“暂时无法确认营业状态/优惠”）。\n"
        "3. 不得擅自改变推荐或对比排行（overall_ranking）。若有 best_for，你可以按它指引的逻辑描述各家店的优势侧重点。\n"
        "4. 输出必须是一个合法的 JSON 对象，格式为：\n"
        "{\n"
        "  \"natural_response\": \"这里写你的自然语言回复内容\"\n"
        "}\n"
        "禁止在 JSON 之外输出任何多余的解释、Markdown 标记或前导文本。"
    )

    user_prompt = (
        "## DecisionPlan 事实数据：\n"
        f"- 意图类型: {plan.answer_type}\n"
        f"- 决策上下文: {json.dumps(plan.decision_context, ensure_ascii=False)}\n"
        f"- 选择的目标店面: {json.dumps(plan.selected_targets, ensure_ascii=False)}\n"
        f"- 未选择/省略的店面: {json.dumps(plan.omitted_targets, ensure_ascii=False)}\n"
        f"- 候选店详情摘要: {json.dumps(plan.candidate_summaries, ensure_ascii=False)}\n"
        f"- 主推荐店: {json.dumps(plan.main_recommendation, ensure_ascii=False)}\n"
        f"- 综合排序: {json.dumps(plan.overall_ranking, ensure_ascii=False)}\n"
        f"- 优势推荐归类 (best_for): {json.dumps(plan.best_for, ensure_ascii=False)}\n"
        f"- 确定性事实点: {json.dumps(plan.factual_points, ensure_ascii=False)}\n"
        f"- 不确定项/无法确认项: {json.dumps(plan.uncertainty_notes, ensure_ascii=False)}\n"
        f"- 必须提及的未确认项: {json.dumps(plan.must_mention_unknowns, ensure_ascii=False)}\n"
        f"- 禁止声明: {json.dumps(plan.forbidden_claims, ensure_ascii=False)}\n\n"
        "## 示例 1（多店对比场景）：\n"
        "输入 DecisionPlan (其中 selected_targets 包含 A 店和 B 店，best_for 包含 B-距离近，A-有券)\n"
        "输出 JSON:\n"
        "{\n"
        "  \"natural_response\": \"这两家店各有特色：\\n- 如果你想省钱，优先看 A 店，因为当前查到有券。\\n- 如果想少走路，B 店更合适，距离你更近。\\n目前信息看，我更推荐 B 店。\"\n"
        "}\n\n"
        "## 示例 2（单店多维度查询场景）：\n"
        "输入 DecisionPlan (selected_targets 包含 A 店，factual_points 包含有券、营业中)\n"
        "输出 JSON:\n"
        "{\n"
        "  \"natural_response\": \"A 这家店可以重点看这几点：当前查到有券，而且距离你比较近；营业状态方面目前是营业中。\"\n"
        "}\n\n"
        "请根据当前的 DecisionPlan 数据，直接输出对应的 JSON。"
    )

    try:
        try:
            res = _invoke_verbalizer_llm(
                llm_client,
                prompt=user_prompt,
                system_prompt=system_prompt,
            )
        except AttributeError:
            if metadata_out is not None:
                metadata_out["answer_fallback_reason"] = "llm_call_missing_callable"
                metadata_out["llm_verbalizer_error"] = "llm_call_missing_callable"
            return fallback_text

        if not res or not res.get("ok"):
            if metadata_out is not None:
                metadata_out["answer_fallback_reason"] = "llm_call_failed"
                metadata_out["llm_verbalizer_error"] = str((res or {}).get("error_message", "") or (res or {}).get("error_code", "") or "llm_call_failed")
            return fallback_text

        content = res.get("content")
        if isinstance(content, VerbalizerResponse):
            natural_text = content.natural_response
        elif isinstance(content, dict):
            natural_text = content.get("natural_response", "")
        else:
            if metadata_out is not None:
                metadata_out["answer_fallback_reason"] = "llm_output_invalid"
                metadata_out["llm_verbalizer_error"] = "missing_natural_response"
            return fallback_text

        if not natural_text:
            if metadata_out is not None:
                metadata_out["answer_fallback_reason"] = "llm_output_invalid"
                metadata_out["llm_verbalizer_error"] = "empty_natural_response"
            return fallback_text

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
            return fallback_text

        return natural_text
    except Exception as exc:
        if metadata_out is not None:
            metadata_out["answer_fallback_reason"] = "llm_verbalizer_exception"
            metadata_out["llm_verbalizer_error"] = str(exc)
        return fallback_text

