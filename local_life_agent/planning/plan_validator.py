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

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - fallback for minimal environments
    class _FallbackValidationError:
        def __init__(self, message: str, path: tuple[str, ...] | list[str] | None = None, validator: str = ""):
            self.message = message
            self.path = list(path or [])
            self.validator = validator

    class Draft7Validator:  # type: ignore[override]
        def __init__(self, schema: dict[str, Any] | None):
            self.schema = schema or {}

        def iter_errors(self, instance: Any):
            yield from _iter_schema_errors(self.schema, instance)


def _iter_schema_errors(schema: dict[str, Any], instance: Any, path: tuple[str, ...] = ()):
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            yield _FallbackValidationError("is not of type 'object'", path, "type")
            return
        required = schema.get("required", [])
        for field in required:
            if field not in instance or instance[field] is None or (isinstance(instance[field], str) and not instance[field].strip()):
                yield _FallbackValidationError(f"'{field}' is a required property", path + (field,), "required")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                yield from _iter_schema_errors(subschema, instance[key], path + (key,))
        return

    if schema_type == "array":
        if not isinstance(instance, list):
            yield _FallbackValidationError("is not of type 'array'", path, "type")
            return
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(instance):
                yield from _iter_schema_errors(items_schema, item, path + (str(idx),))
        return

    if schema_type == "string":
        if not isinstance(instance, str):
            yield _FallbackValidationError("is not of type 'string'", path, "type")
            return
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            yield _FallbackValidationError(
                f"'' is too short" if not instance else f"'{instance}' is too short",
                path,
                "minLength",
            )
        enum = schema.get("enum")
        if isinstance(enum, list) and instance not in enum:
            yield _FallbackValidationError(
                f"'{instance}' is not one of {enum}",
                path,
                "enum",
            )
        return

    if schema_type == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            yield _FallbackValidationError("is not of type 'number'", path, "type")
        return

    if schema_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            yield _FallbackValidationError("is not of type 'integer'", path, "type")
        return

    if schema_type == "boolean":
        if not isinstance(instance, bool):
            yield _FallbackValidationError("is not of type 'boolean'", path, "type")
        return

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
            "single_shop_query": ["search_shops"],
            "coupon_query": ["search_shops"],
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
        self._check_comparison_target_limit(plan, report)
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

            if plan.task_type == "recommendation":
                args = dict(tc.args or {}) if isinstance(tc.args, dict) else {}
                shop_id = str(args.get("shop_id", "")).strip()
                placeholder = shop_id.startswith("$search_result[") and shop_id.endswith(".shop_id")
                if placeholder:
                    continue
                shop_ids = args.get("shop_ids")
                if isinstance(shop_ids, str) and shop_ids.strip() == "$search_result.shop_ids":
                    continue
                if isinstance(shop_ids, list) and any(
                    isinstance(item, str) and item.strip().startswith("$search_result[") for item in shop_ids
                ):
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
            sid = tc.target_shop_id.strip()
            arg_shop_id = str(tc.args.get("shop_id", "")).strip() if isinstance(tc.args, dict) else ""
            if plan.task_type == "recommendation":
                if sid.startswith("$search_result[") or arg_shop_id.startswith("$search_result["):
                    continue
            if sid and sid not in resolved_shop_ids:
                report.errors.append(
                    f"shop_id '{sid}' in call_id={tc.call_id} was not produced "
                    f"by legitimate resolve. Allowed: {resolved_shop_ids}"
                )
            if arg_shop_id and arg_shop_id not in resolved_shop_ids:
                report.errors.append(
                    f"shop_id '{arg_shop_id}' in args for call_id={tc.call_id} was not produced "
                    f"by legitimate resolve. Allowed: {resolved_shop_ids}"
                )
            if sid and arg_shop_id and sid != arg_shop_id:
                report.errors.append(
                    f"shop_id mismatch in call_id={tc.call_id}: target_shop_id='{sid}' args.shop_id='{arg_shop_id}'"
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

    def _check_comparison_target_limit(self, plan: ExecutionPlan, report: ValidationReport) -> None:
        if plan.task_type != "comparison":
            return

        target_shop_ids = [str(item).strip() for item in plan.target_shop_ids or [] if str(item).strip()]
        if len(target_shop_ids) > config.COMPARISON_MAX_SHOP_LIMIT:
            report.errors.append(
                f"comparison_target_limit_exceeded: plan.target_shop_ids has {len(target_shop_ids)} items > {config.COMPARISON_MAX_SHOP_LIMIT}"
            )

        for tc in plan.tool_calls:
            if tc.tool_name not in {"get_shop_cards", "get_shop_review_summary"}:
                continue
            args = dict(tc.args or {}) if isinstance(tc.args, dict) else {}
            shop_ids = args.get("shop_ids")
            if isinstance(shop_ids, list):
                concrete_shop_ids = [
                    str(item).strip()
                    for item in shop_ids
                    if isinstance(item, str) and str(item).strip() and not str(item).strip().startswith("$search_result")
                ]
                if len(concrete_shop_ids) > config.COMPARISON_MAX_SHOP_LIMIT:
                    report.errors.append(
                        f"comparison_target_limit_exceeded: tool '{tc.tool_name}' (call_id={tc.call_id}) args.shop_ids has {len(concrete_shop_ids)} items > {config.COMPARISON_MAX_SHOP_LIMIT}"
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
