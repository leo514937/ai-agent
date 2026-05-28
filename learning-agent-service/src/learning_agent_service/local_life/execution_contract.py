from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .schemas import LocalLifeModel


class ExecutionContract(LocalLifeModel):
    raw_query: str
    resolved_query: str = ""
    intent: str = ""
    resolved_shop_id: Optional[int] = None
    resolved_shop_name: Optional[str] = None
    candidate_shop_ids: List[int] = Field(default_factory=list)
    required_facets: List[str] = Field(default_factory=list)
    execute_rag: bool = False
    execute_tools: List[str] = Field(default_factory=list)
    city: Optional[str] = None
    area: Optional[str] = None
    category: Optional[str] = None
    shop_type_id: Optional[int] = None
    price_max: Optional[float] = None
    scene_keywords: List[str] = Field(default_factory=list)
    negative_categories: List[str] = Field(default_factory=list)
    clarification_action: Optional[str] = None
    forbid_global_fallback: bool = False
    reason: str = ""
    source: str = "session"
    shop_context_source: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)

