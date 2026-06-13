from __future__ import annotations

from learning_agent_service.application.dependencies_impl import AppDependencies, build_dependencies
from learning_agent_service.application.router.phase0_quality import build_initial_routing_decision
from learning_agent_service.application.routing_primitives import _looks_like_unserviceable_location, build_input_quality, normalize_query
from learning_agent_service.domain.contracts import PersistentSessionContext


def test_routing_primitives_still_work() -> None:
    text = "\u6e56\u7554\u79c1\u623f\u83dc\u9002\u5408\u5e26\u7236\u6bcd\u5417"

    assert normalize_query(text) == text
    assert build_input_quality(text).is_valid is True
    assert _looks_like_unserviceable_location("\u5317\u6781") is True

    persistent = PersistentSessionContext.model_construct(current_topic="\u6e56\u7554\u79c1\u623f\u83dc", extra={})
    routing = build_initial_routing_decision(text, persistent)

    assert routing.required_action == "rag_retrieval"
    assert routing.should_retrieve is True


def test_dependency_module_exports_public_entrypoint() -> None:
    assert AppDependencies is not None
    assert callable(build_dependencies)
