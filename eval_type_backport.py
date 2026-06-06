from __future__ import annotations

import ast
import builtins
import types
from typing import Any
import typing


def eval_type_backport(
    value: Any,
    globalns: dict[str, Any] | None = None,
    localns: dict[str, Any] | None = None,
    try_default: bool = False,
) -> Any:
    """Minimal shim for pydantic's optional eval_type_backport dependency.

    This keeps Python 3.10 working in environments where the extra package is not
    installed, while still allowing modern annotations such as `str | None`.
    """

    if isinstance(value, typing.ForwardRef):
        expr = value.__forward_arg__
    elif isinstance(value, str):
        expr = value
    else:
        return value

    namespace: dict[str, Any] = {"__builtins__": builtins.__dict__}
    if globalns:
        namespace.update(globalns)
    if localns:
        namespace.update(localns)

    try:
        if "|" in expr:
            return _eval_annotation_expr(ast.parse(expr, mode="eval").body, namespace)
        return eval(expr, namespace, namespace)
    except Exception:
        if try_default:
            return value
        raise


def _resolve_name(name: str, namespace: dict[str, Any]) -> Any:
    if name == "None":
        return type(None)
    if name in namespace:
        return namespace[name]
    if hasattr(typing, name):
        return getattr(typing, name)
    if hasattr(types, name):
        return getattr(types, name)
    if hasattr(builtins, name):
        return getattr(builtins, name)
    raise NameError(name)


def _eval_annotation_expr(node: ast.AST, namespace: dict[str, Any]) -> Any:
    if isinstance(node, ast.Name):
        return _resolve_name(node.id, namespace)
    if isinstance(node, ast.Constant):
        if node.value is None:
            return type(None)
        return node.value
    if isinstance(node, ast.Attribute):
        return getattr(_eval_annotation_expr(node.value, namespace), node.attr)
    if isinstance(node, ast.Subscript):
        target = _eval_annotation_expr(node.value, namespace)
        slice_value = _eval_annotation_expr(node.slice, namespace)
        return target[slice_value]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_annotation_expr(elt, namespace) for elt in node.elts)
    if isinstance(node, ast.List):
        return [_eval_annotation_expr(elt, namespace) for elt in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _eval_annotation_expr(node.left, namespace)
        right = _eval_annotation_expr(node.right, namespace)
        if left is type(None):
            return typing.Optional[right]
        if right is type(None):
            return typing.Optional[left]
        return typing.Union[left, right]
    raise TypeError(f"Unsupported annotation node: {ast.dump(node, include_attributes=False)}")
