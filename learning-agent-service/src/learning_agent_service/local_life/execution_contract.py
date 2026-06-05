from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas import LocalLifeModel


class FacetExecutionItem(BaseModel):
    facet: str
    source: Literal["tool", "rag", "tool_plus_rag", "context"]
    tool_name: str | None = None
    retrieval_mode: str | None = None
    required: bool = True

class ExecutionContract(LocalLifeModel):
    raw_query: str
    resolved_query: str = ""
    intent: str = ""
    resolved_shop_id: int | None = None
    resolved_shop_name: str | None = None
    candidate_shop_ids: list[int] = Field(default_factory=list)
    required_facets: list[str] = Field(default_factory=list)
    execute_rag: bool = False
    execute_tools: list[str] = Field(default_factory=list)
    city: str | None = None
    area: str | None = None
    category: str | None = None
    shop_type_id: int | None = None
    price_max: float | None = None
    scene_keywords: list[str] = Field(default_factory=list)
    negative_categories: list[str] = Field(default_factory=list)
    clarification_action: str | None = None
    forbid_global_fallback: bool = False
    reason: str = ""
    source: str = "session"
    shop_context_source: str | None = None
    target_shop: Any | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    
    # Day3 Unification: Consolidating FacetExecutionPlan directly inside ExecutionContract 
    items: list[FacetExecutionItem] = Field(default_factory=list)


