"""Tool argument validation helpers."""

from __future__ import annotations

from typing import Any


def validate_tool_args(tool_name: str, tool_def: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """Validate tool arguments against the input schema.

    Returns a list of error messages. Empty list means valid.
    """

    if not isinstance(tool_def, dict):
        return [f"Tool '{tool_name}' not registered"]

    schema = tool_def.get("input_schema", {})
    required = schema.get("required", [])
    errors: list[str] = []
    for field in required:
        if field not in args or args[field] is None or (isinstance(args[field], str) and not args[field].strip()):
            errors.append(f"Missing required argument '{field}' for tool '{tool_name}'")

    props = schema.get("properties", {})
    for field, value in args.items():
        if field not in props:
            continue
        prop_schema = props[field]
        prop_type = prop_schema.get("type")
        if prop_type == "string" and not isinstance(value, str):
            errors.append(f"Argument '{field}' must be a string")
        elif prop_type == "number" and not isinstance(value, (int, float)) and not isinstance(value, bool):
            errors.append(f"Argument '{field}' must be a number")
        elif prop_type == "integer" and not isinstance(value, int) and not isinstance(value, bool):
            errors.append(f"Argument '{field}' must be an integer")
        elif prop_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Argument '{field}' must be a boolean")
        elif prop_type == "array" and not isinstance(value, list):
            errors.append(f"Argument '{field}' must be a list")
        elif prop_type == "object" and not isinstance(value, dict):
            errors.append(f"Argument '{field}' must be a dict")
    return errors

