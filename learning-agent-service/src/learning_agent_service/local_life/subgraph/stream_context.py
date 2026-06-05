from dataclasses import dataclass, field
from typing import Any, Mapping

from learning_agent_service.domain import ChatTurnCommand, PersistentSessionContext


@dataclass
class StreamRunContext:
    command: ChatTurnCommand
    persistent: PersistentSessionContext
    client_context: Mapping[str, Any]
    session_context: dict[str, Any]
    clean_session_context: dict[str, Any]
    session_current_shop_before: Any
    session_current_shop_id_before: Any
    last_candidates_before: list[Any]
    low_information_input: bool
    understanding_hint: Any = None
    understanding: Any = None
    slots: Any = None
    clarification: Any = None
    intent: Any = None
    user_need: Any = None
    arbitration_result: Any = None
    input_context: Any = None
    perception_context: Any = None
    memory_arbitration: Any = None
    state: Any = None
    query_route: Any = None
    review_result: Any = None
    execution_requirements: Any = None
    execution_contract: Any = None
    target_shop: Any = None
    answer_contract: Any = None
    resolved_shop_ids: list[int] = field(default_factory=list)
    selected_shop: Any = None
    structured_candidates: list[Any] = field(default_factory=list)
    ranked_candidates: list[Any] = field(default_factory=list)
    evidence_claims: list[Any] = field(default_factory=list)
    source_summary: dict[str, Any] = field(default_factory=dict)
    qdrant_pack: Any = None
    facet_bundle: Any = None
    coupon_result_obj: Any = None
    safety_result: Any = None
    tool_plan: Any = None
    tool_name: Any = None
    tool_output: Any = None
    extra_tool_outputs: list[tuple[Any, Any]] = field(default_factory=list)
    first_shop_name: str | None = None
    tool_input_summary: dict[str, Any] = field(default_factory=dict)
    top_shop: Any = None
    response_hint: Any = None
    verification_result: Any = None

