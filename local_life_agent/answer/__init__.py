"""Answer package compatibility layer."""

from __future__ import annotations

import importlib
import sys

_MODULE_ALIASES = {
    "candidate_decision": "..planning.decision.candidate_decision",
    "evidence_builder": "..planning.evidence.evidence_builder",
}

for legacy_name, target in _MODULE_ALIASES.items():
    module = importlib.import_module(target, package=__name__)
    sys.modules[f"{__name__}.{legacy_name}"] = module
