"""DEPRECATED_COMPAT: answer 规划、生成、校验的兼容壳。

Phase 1 只冻结既有导出面，不新增旧路径依赖。
"""

from __future__ import annotations

from typing import Any

from ..domain.decision import decision_to_answer_plan


def generate_answer(*args: Any, **kwargs: Any):
    from ..answer.generator import generate_answer as _generate_answer

    return _generate_answer(*args, **kwargs)


def verify_answer(*args: Any, **kwargs: Any):
    from ..answer.verifier import verify_answer as _verify_answer

    return _verify_answer(*args, **kwargs)


class ResponseCore:
    def build_answer_plan(self, *args: Any, **kwargs: Any):
        decision_plan = args[0] if args else None
        evidence_pack = args[1] if len(args) > 1 else kwargs.get("evidence_pack")
        if decision_plan is None:
            return {}
        return decision_to_answer_plan(decision_plan, evidence_pack)

    def generate(self, *args: Any, **kwargs: Any):
        return generate_answer(*args, **kwargs)

    def verify(self, *args: Any, **kwargs: Any):
        return verify_answer(*args, **kwargs)
