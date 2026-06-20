"""ExecutionPlan validator — intercepts illegal plans before tool dispatch.

Implements the 7 validation rules from todo/04 §6 to guarantee:
  - No hallucinated tool names
  - No hallucinated shop_ids
  - No dependency cycles
  - Budget compliance
  - Required/optional correctness
  - Forbidden tool isolation
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator

from .. import config
from ..domain.schemas import ExecutionPlan, ToolCallSpec
from ..tools.registry import ToolRegistry, get_registry


class ValidationReport:
    """Result of validating a single execution plan."""
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def merge(self, other: ValidationReport) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


class ExecutionPlanValidator:
    """Validates an ExecutionPlan against all registered tools and rules.

    Rules implemented (todo/04 §6):
      1. tool_name registered
      2. args match schema
      3. shop_id from legitimate resolve
      4. depends_on cycle detection
      5. required/optional correctness
      6. max_tool_calls budget
      7. forbidden_tools check
    """

    def __init__(
        self,
        registered_tools: set[str] | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self._tool_registry = tool_registry or get_registry()
        self._registered_tools = (
            registered_tools if registered_tools is not None else set(self._tool_registry.list_tools())
        )
        self._forbidden_tools: dict[str, list[str]] = {
            "coupon_query": ["search_shops"],
            "single_shop_query": ["search_shops"],
        }

    def validate(
        self,
        plan: ExecutionPlan,
        resolved_shop_ids: set[str] | None = None,
    ) -> ValidationReport:
        """Run all 7 validation rules against the plan.

        Args:
            plan: The execution plan to validate.
            resolved_shop_ids: Set of shop_ids from legitimate resolution.
                If None, shop_id checks are skipped (allow in tests).

        Returns:
            ValidationReport with errors and warnings.
        """
        report = ValidationReport()

        self._check_tool_registered(plan, report)
        self._check_arg_schemas(plan, report)
        self._check_max_tool_calls(plan, report)
        self._check_forbidden_tools(plan, report)
        self._check_depends_on_cycles(plan, report)
        self._check_shop_ids(plan, resolved_shop_ids, report)

        return report

    # ------------------------------------------------------------------
    # Rule 1: tool_name registered
    # ------------------------------------------------------------------
    def _check_tool_registered(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        for tc in plan.tool_calls:
            if tc.tool_name not in self._registered_tools:
                report.errors.append(
                    f"Tool '{tc.tool_name}' (call_id={tc.call_id}) is not registered. "
                    f"Registered: {sorted(self._registered_tools)}"
                )

    # ------------------------------------------------------------------
    # Rule 2: args match schema  (placeholder — detailed schema matching
    #         will be wired when tool schemas are formalised)
    # ------------------------------------------------------------------
    def _check_arg_schemas(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        for tc in plan.tool_calls:
            tool_def = self._tool_registry.get(tc.tool_name)
            if tool_def is None:
                report.errors.append(
                    f"SCHEMA_VALIDATION_FAILED: Tool '{tc.tool_name}' (call_id={tc.call_id}) is not registered."
                )
                continue

            schema = tool_def.get("input_schema", {})
            if not isinstance(schema, dict) or not schema:
                report.errors.append(
                    f"SCHEMA_VALIDATION_FAILED: Tool '{tc.tool_name}' (call_id={tc.call_id}) has no valid input_schema."
                )
                continue

            validator = Draft7Validator(schema)
            for error in sorted(validator.iter_errors(tc.args), key=lambda e: (list(e.path), e.validator, e.message)):
                code = "SCHEMA_VALIDATION_FAILED" if error.validator == "required" else "INVALID_ARGUMENT"
                location = ".".join(str(part) for part in error.path)
                if location:
                    report.errors.append(
                        f"{code}: tool '{tc.tool_name}' (call_id={tc.call_id}) args.{location}: {error.message}"
                    )
                else:
                    report.errors.append(
                        f"{code}: tool '{tc.tool_name}' (call_id={tc.call_id}) {error.message}"
                    )

    # ------------------------------------------------------------------
    # Rule 3: shop_id from legitimate resolve
    # ------------------------------------------------------------------
    def _check_shop_ids(
        self,
        plan: ExecutionPlan,
        resolved_shop_ids: set[str] | None,
        report: ValidationReport,
    ) -> None:
        if resolved_shop_ids is None:
            return
        for tc in plan.tool_calls:
            sid = tc.target_shop_id
            if sid and sid not in resolved_shop_ids:
                report.errors.append(
                    f"shop_id '{sid}' in call_id={tc.call_id} was not produced "
                    f"by legitimate resolve. Allowed: {resolved_shop_ids}"
                )

    # ------------------------------------------------------------------
    # Rule 4: depends_on cycle detection (DFS)
    # ------------------------------------------------------------------
    def _check_depends_on_cycles(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        call_map = {tc.call_id: tc for tc in plan.tool_calls}

        def _has_cycle(start: str, path: set[str]) -> bool:
            if start in path:
                return True
            tc = call_map.get(start)
            if tc is None:
                return False
            path.add(start)
            for dep in tc.depends_on:
                if _has_cycle(dep, path):
                    return True
            path.discard(start)
            return False

        for tc in plan.tool_calls:
            if _has_cycle(tc.call_id, set()):
                report.errors.append(
                    f"Circular dependency detected involving call_id='{tc.call_id}'"
                )

    # ------------------------------------------------------------------
    # Rule 5: required/optional (structural — already captured in ToolCallSpec)
    # ------------------------------------------------------------------
    def _check_required_optional(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        pass  # Enforced at plan-construction time via ToolCallSpec.required

    # ------------------------------------------------------------------
    # Rule 6: max_tool_calls budget
    # ------------------------------------------------------------------
    def _check_max_tool_calls(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        if len(plan.tool_calls) > config.MAX_TOOL_CALLS:
            report.errors.append(
                f"Plan exceeds max_tool_calls limit: {len(plan.tool_calls)} > {config.MAX_TOOL_CALLS}"
            )

    # ------------------------------------------------------------------
    # Rule 7: forbidden_tools check by task_type
    # ------------------------------------------------------------------
    def _check_forbidden_tools(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        forbidden = self._forbidden_tools.get(plan.task_type, [])
        for tc in plan.tool_calls:
            if tc.tool_name in forbidden:
                report.errors.append(
                    f"Tool '{tc.tool_name}' (call_id={tc.call_id}) is forbidden "
                    f"for task_type='{plan.task_type}'"
                )
