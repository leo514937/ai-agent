from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from learning_agent_service.domain.utils import clean_text as _clean_text

from .answer_contract import AnswerContract
from .realtime_contract import get_realtime_contract


class PlannedToolInput(BaseModel):
    tool_name: str
    facet: str
    shop_id: int | None = None
    shop_name: str | None = None
    source_scope: Literal["target_shop", "recommendation_candidate", "fallback_candidate"] = "target_shop"


class ToolPlan(BaseModel):
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    tool_inputs: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    runs: list[PlannedToolInput] = Field(default_factory=list)
    execution_mode: Literal["none", "single_shop", "per_candidate"] = "none"
    timeout_budget_ms: int = 3000
    fallback_policy: str = "strict_realtime_contract"
    source_intent: str = ""
    latest_turn_message: str = ""
    current_intent: str = ""
    blocked_by_realtime_contract: bool = False
    blocked_reason: str | None = None
    forbidden_facets: list[str] = Field(default_factory=list)
    target_shop_id: int | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)


def _target_shop_id(target_shop: Any | None) -> int | None:
    if target_shop is None:
        return None
    value = getattr(target_shop, "shop_id", None)
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _target_shop_name(target_shop: Any | None) -> str | None:
    if target_shop is None:
        return None
    return _clean_text(getattr(target_shop, "shop_name", None))


class LocalLifeToolPlanner:
    @classmethod
    def plan(
        cls,
        *,
        answer_contract: AnswerContract | None,
        target_shop: Any | None,
        user_need: Any | None,
        latest_turn_message: str,
        current_intent: str | None,
        ranked_candidates: Sequence[Any] | None = None,
    ) -> ToolPlan:
        contract = answer_contract
        latest_turn_message = str(latest_turn_message or "")
        ranked_candidates = list(ranked_candidates or [])
        current_intent = str(current_intent or getattr(user_need, "intent", "") or "")

        if contract is None:
            return ToolPlan(
                latest_turn_message=latest_turn_message,
                current_intent=current_intent,
                source_intent=current_intent,
            )

        realtime_facets = [facet for facet in list(contract.realtime_facets or []) if get_realtime_contract(facet) is not None]
        required_tools: list[str] = []
        runs: list[PlannedToolInput] = []
        candidate_shop_ids: list[int] = []

        is_recommendation_scope = contract.answer_style == "multi_shop_recommendation" and bool(ranked_candidates)
        plan_target_shop_id = None if is_recommendation_scope else _target_shop_id(target_shop)

        for candidate in ranked_candidates:
            try:
                candidate_id = int(getattr(candidate, "shop_id", None))
            except Exception:
                continue
            if candidate_id not in candidate_shop_ids:
                candidate_shop_ids.append(candidate_id)

        for facet in realtime_facets:
            realtime_contract = get_realtime_contract(facet)
            if realtime_contract is None:
                continue
            tool_name = realtime_contract.allowed_tools[0]
            if tool_name not in required_tools:
                required_tools.append(tool_name)

            if is_recommendation_scope:
                for candidate in ranked_candidates:
                    try:
                        shop_id = int(getattr(candidate, "shop_id", None))
                    except Exception:
                        continue
                    shop_name = _clean_text(getattr(candidate, "name", None))
                    runs.append(
                        PlannedToolInput(
                            tool_name=tool_name,
                            facet=facet,
                            shop_id=shop_id,
                            shop_name=shop_name,
                            source_scope="recommendation_candidate",
                        )
                    )
            elif plan_target_shop_id is not None:
                runs.append(
                    PlannedToolInput(
                        tool_name=tool_name,
                        facet=facet,
                        shop_id=plan_target_shop_id,
                        shop_name=_target_shop_name(target_shop),
                        source_scope="target_shop",
                    )
                )
            elif ranked_candidates:
                candidate = ranked_candidates[0]
                try:
                    shop_id = int(getattr(candidate, "shop_id", None))
                except Exception:
                    shop_id = None
                runs.append(
                    PlannedToolInput(
                        tool_name=tool_name,
                        facet=facet,
                        shop_id=shop_id,
                        shop_name=_clean_text(getattr(candidate, "name", None)),
                        source_scope="fallback_candidate",
                    )
                )

        deduped_runs: list[PlannedToolInput] = []
        seen_run_keys: set[tuple[str, str, str]] = set()
        for item in runs:
            key = (
                item.tool_name,
                str(item.shop_id) if item.shop_id is not None else "",
                item.source_scope,
            )
            if key in seen_run_keys:
                continue
            seen_run_keys.add(key)
            deduped_runs.append(item)

        tool_inputs: dict[str, list[dict[str, Any]]] = {}
        for item in deduped_runs:
            tool_inputs.setdefault(item.tool_name, []).append(item.model_dump(mode="json"))

        blocked = bool(realtime_facets) and not bool(deduped_runs)
        blocked_reason = None
        if blocked:
            if is_recommendation_scope:
                blocked_reason = "recommendation_candidates_missing"
            else:
                blocked_reason = "target_shop_missing"

        return ToolPlan(
            required_tools=required_tools,
            optional_tools=[],
            tool_inputs=tool_inputs,
            runs=deduped_runs,
            execution_mode="per_candidate" if is_recommendation_scope and deduped_runs else ("single_shop" if deduped_runs else "none"),
            timeout_budget_ms=3000 if len(deduped_runs) <= 3 else 5000,
            fallback_policy="strict_realtime_contract",
            source_intent=current_intent or contract.answer_style,
            latest_turn_message=latest_turn_message,
            current_intent=current_intent,
            blocked_by_realtime_contract=blocked,
            blocked_reason=blocked_reason,
            forbidden_facets=list(contract.forbidden_facets or []),
            target_shop_id=plan_target_shop_id,
            candidate_shop_ids=candidate_shop_ids,
        )
