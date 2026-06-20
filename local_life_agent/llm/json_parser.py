"""JSON response parser for LLM outputs.

The parser is conservative: it accepts plain JSON, fenced JSON blocks,
and text with JSON embedded inside explanatory prose. If it cannot
recover a JSON object, it raises ``LLMJSONParseError``.
"""

from __future__ import annotations

import json
import re
from typing import Any


class LLMJSONParseError(ValueError):
    """Raised when an LLM response cannot be turned into a JSON object."""


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _try_load_json(candidate: Any) -> dict[str, Any] | None:
    if isinstance(candidate, dict):
        return dict(candidate)
    if not isinstance(candidate, str):
        return None

    text = candidate.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        raise LLMJSONParseError("LLM_JSON_PARSE_ERROR: expected a JSON object")
    return parsed


def _extract_balanced_fragment(text: str) -> str | None:
    """Extract the first balanced JSON-like fragment from *text*."""
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not starts:
        return None
    start = min(starts)

    stack: list[str] = []
    in_string = False
    escaped = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                continue
            opener = stack.pop()
            if opener == "{" and ch != "}":
                continue
            if opener == "[" and ch != "]":
                continue
            if not stack:
                return text[start : idx + 1]

    return None


def parse_json_response(raw: Any) -> dict[str, Any]:
    """Extract and validate a JSON object from LLM output."""
    direct = _try_load_json(raw)
    if direct is not None:
        return direct

    if not isinstance(raw, str):
        raise LLMJSONParseError("LLM_JSON_PARSE_ERROR: response is not a string")

    raw_text = raw.strip()
    if not raw_text:
        raise LLMJSONParseError("LLM_JSON_PARSE_ERROR: empty response")

    # 1) Prefer fenced JSON blocks.
    for match in _CODE_FENCE_RE.finditer(raw_text):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        direct = _try_load_json(candidate)
        if direct is not None:
            return direct

    # 2) Try the first balanced object/array fragment from prose.
    fragment = _extract_balanced_fragment(raw_text)
    if fragment is not None:
        direct = _try_load_json(fragment)
        if direct is not None:
            return direct

    # 3) As a last resort, scan for the first fenced block-like JSON
    #    inside raw text even if there are stray backticks / labels.
    json_start = raw_text.find("{")
    json_end = raw_text.rfind("}")
    if json_start != -1 and json_end != -1 and json_end > json_start:
        direct = _try_load_json(raw_text[json_start : json_end + 1])
        if direct is not None:
            return direct

    raise LLMJSONParseError("LLM_JSON_PARSE_ERROR: could not extract JSON object")
