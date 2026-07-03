"""Helpers for validating and normalizing GraphState-shaped payloads."""

from __future__ import annotations

from typing import Any

from .graph_state_model import (
    GRAPH_STATE_FIELD_CONTRACTS,
    GraphStateModel,
    GraphStateModelAdapterError,
    GraphStateValidationResult,
    validate_graph_state,
)

__all__ = [
    "GRAPH_STATE_FIELD_CONTRACTS",
    "GraphStateModel",
    "GraphStateModelAdapterError",
    "GraphStateValidationResult",
    "validate_graph_state",
]


def describe_graph_state_contracts() -> list[dict[str, Any]]:
    """Return a serialisable snapshot of the current field ownership map."""

    return [contract.model_dump(mode="python") for contract in GRAPH_STATE_FIELD_CONTRACTS.values()]
