import importlib
import sys

import pytest

from learning_agent_service.application.workflow.adapters.helpers import build_initial_routing_decision
from learning_agent_service.application.workflow.adapters.helpers import routing_trace_payload
from learning_agent_service.domain.contracts import PersistentSessionContext


def test_legacy_routing_module_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("learning_agent_service.application.routing")


def test_router_package_no_longer_reexports_root_api() -> None:
    router_pkg = importlib.import_module("learning_agent_service.application.router")
    assert not hasattr(router_pkg, "build_initial_routing_decision")
    assert not hasattr(router_pkg, "routing_trace_payload")


def test_router_submodules_still_provide_routing_helpers() -> None:
    assert callable(build_initial_routing_decision)
    assert callable(routing_trace_payload)
    routing = build_initial_routing_decision("你好", PersistentSessionContext())
    assert routing.required_action == "direct_answer"
    assert routing.route_candidate == "greeting"


def test_config_root_import_does_not_load_rag_hybrid() -> None:
    sys.modules.pop("learning_agent_service.rag.hybrid", None)
    sys.modules.pop("learning_agent_service.config", None)
    config_pkg = importlib.import_module("learning_agent_service.config")
    assert hasattr(config_pkg, "get_settings")
    assert "learning_agent_service.rag.hybrid" not in sys.modules
