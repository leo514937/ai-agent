from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvaluationDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    description: str
    weight: float = 1.0
    score_min: int = 0
    score_max: int = 5


class EvaluationRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric_name: str = "local_life_agent_rubric"
    dimensions: list[EvaluationDimension] = Field(default_factory=list)


DEFAULT_EVALUATION_RUBRIC = EvaluationRubric(
    dimensions=[
        EvaluationDimension(key="route_correctness", description="路由是否正确"),
        EvaluationDimension(key="facet_recall", description="是否找全所需 facet"),
        EvaluationDimension(key="facet_precision", description="是否引入多余 facet"),
        EvaluationDimension(key="target_resolution_correctness", description="目标解析是否正确"),
        EvaluationDimension(key="tool_plan_correctness", description="工具计划是否合理"),
        EvaluationDimension(key="evidence_grounding", description="回答是否基于证据"),
        EvaluationDimension(key="unsupported_claim_rate", description="是否包含不支持的断言"),
        EvaluationDimension(key="clarification_correctness", description="澄清是否恰当"),
        EvaluationDimension(key="state_update_correctness", description="状态写回是否正确"),
        EvaluationDimension(key="answer_helpfulness", description="回答是否有帮助"),
        EvaluationDimension(key="latency_bucket", description="延迟是否落在可接受区间"),
    ]
)


def rubric_dimension_keys(rubric: EvaluationRubric | None = None) -> list[str]:
    source = rubric or DEFAULT_EVALUATION_RUBRIC
    return [dimension.key for dimension in source.dimensions]
