import importlib

import pytest

from learning_agent_service.application.router import build_initial_routing_decision, routing_trace_payload
from learning_agent_service.domain.contracts import PersistentSessionContext


def test_legacy_routing_module_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("learning_agent_service.application.routing")


def test_router_package_exports_are_available() -> None:
    assert callable(build_initial_routing_decision)
    assert callable(routing_trace_payload)


def test_router_package_can_build_basic_decision() -> None:
    routing = build_initial_routing_decision("你好", PersistentSessionContext())
    assert routing.required_action == "direct_answer"
    assert routing.route_candidate == "greeting"
