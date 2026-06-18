import json
from typing import Any

from learning_agent_service.local_life.schemas import CandidateShop, SemanticSelectionResult
from learning_agent_service.infrastructure.db.openai_client import OpenAIRuntime
from learning_agent_service.config.settings_impl import get_settings


class SemanticSelector:
    SYSTEM_PROMPT = """你是一个本地生活实体指代消解引擎。你的任务是从候选店铺列表中，选出用户提问所指代的特定店铺，或者判断用户意图并提供比较对象。

## 候选列表 (Candidate Shops)
{candidates_json}

## 用户意图分类 (follow_up_kind)
- entity_reference: 用户使用了代词（如“这家”、“这家店”）或明确指定了候选列表中的某个店。
- intent_ellipsis: 用户省略了主体，直接询问“便宜点的呢”或“有没有券”。
- comparison_completion: 用户在比较两家或多家店（如“跟海底捞比呢”）。
- constraint_inheritance: 用户提出了新的约束条件（如“换一家川菜”），但依然在当前讨论范围内。
- none: 无法判断或不属于上述情况。

## 你的任务
根据用户的 Query 和对话上下文，返回 JSON 格式的判定结果。

## 约束要求
- anchor_shop_id: 如果用户明确指向候选列表中的某个店，填入其 shop_id。如果没有，则填 null。
- comparison_targets: 如果是比较意图，列出所有的目标店（如果在候选列表中，包含 shop_id，否则只提供 name）。
- 严格输出 JSON 格式。

## JSON 输出格式
{
    "follow_up_kind": "entity_reference",
    "anchor_shop_id": 1004,
    "comparison_targets": [{"name": "海底捞"}],
    "confidence": 0.95
}
"""

    def __init__(self, runtime: OpenAIRuntime | None = None):
        self.runtime = runtime

    def select(
        self,
        query: str,
        candidates: list[CandidateShop],
        session_context: dict[str, Any] | None = None,
    ) -> SemanticSelectionResult:
        if not candidates:
            return SemanticSelectionResult()

        if self.runtime is None:
            # Fallback to simple rule if no runtime available
            exact = [c for c in candidates if c.match_type == "exact"]
            if exact:
                return SemanticSelectionResult(
                    follow_up_kind="entity_reference",
                    anchor_shop_id=exact[0].shop_id,
                    confidence=exact[0].score
                )
            best_cand = candidates[0]
            if best_cand.score > 0.8 and best_cand.match_type == "session":
                from learning_agent_service.local_life.entity_resolver import _explicit_entity_from_query
                from learning_agent_service.local_life.target_shop_policy import _PRONOUNS
                m = _explicit_entity_from_query(query)
                if not m or m in _PRONOUNS:
                    return SemanticSelectionResult(
                        follow_up_kind="entity_reference",
                        anchor_shop_id=best_cand.shop_id,
                        confidence=best_cand.score
                    )
            return SemanticSelectionResult()

        candidates_json = json.dumps(
            [{"shop_id": c.shop_id, "name": c.canonical_name, "match_type": c.match_type, "score": c.score} for c in candidates],
            ensure_ascii=False, indent=2
        )
        
        system_prompt = self.SYSTEM_PROMPT.format(candidates_json=candidates_json)
        
        user_message = f"用户提问: {query}\n"
        if session_context:
            user_message += f"上下文: {json.dumps(session_context, ensure_ascii=False)}\n"

        try:
            cfg = get_settings()
            model = cfg.hybrid_router.hybrid_router_llm_model or self.runtime.default_model
            response = self.runtime.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,
                max_tokens=500,
                timeout=3.0,
                response_format={ "type": "json_object" }
            )

            json_str = response.choices[0].message.content.strip() if response.choices else "{}"
            if json_str.startswith("```"):
                json_str = json_str.split("\n", 1)[1]
                if json_str.endswith("```"):
                    json_str = json_str[:-3]
                    
            data = json.loads(json_str)
            return SemanticSelectionResult(
                follow_up_kind=data.get("follow_up_kind", "none"),
                anchor_shop_id=data.get("anchor_shop_id"),
                comparison_targets=data.get("comparison_targets", []),
                confidence=float(data.get("confidence", 0.0))
            )
        except Exception:
            # Fallback on LLM failure
            pass

        # Fallback to top candidate
        best_cand = candidates[0]
        return SemanticSelectionResult(
            follow_up_kind="entity_reference",
            anchor_shop_id=best_cand.shop_id,
            confidence=0.5
        )
