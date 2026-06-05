from __future__ import annotations

from .execution_contract import ExecutionContract as FacetExecutionPlan

# Backward compatibility alias - Day 3 Unification
from .execution_contract import FacetExecutionItem

__all__ = ["FacetExecutionItem", "FacetExecutionPlan"]
