from __future__ import annotations

from typing import Any


def format_evidence_pack(pack: Any) -> str:
    lines = [
        f"Query: {getattr(pack, 'query', '')}",
        f"Route: {getattr(pack, 'route', '')}",
        f"Strategy: {getattr(pack, 'retrieval_strategy', '')}",
    ]
    parent_evidences = list(getattr(pack, "parent_evidences", []) or [])
    if not parent_evidences:
        lines.append("No evidence found.")
        return "\n".join(lines)
    for index, parent in enumerate(parent_evidences, start=1):
        matched_chunks = list(getattr(parent, "matched_chunks", []) or [])
        sibling_chunks = list(getattr(parent, "sibling_chunks", []) or [])
        matched_roles = ", ".join(getattr(chunk, "chunk_role", "") for chunk in matched_chunks if getattr(chunk, "chunk_role", "")) or "-"
        sibling_roles = ", ".join(getattr(chunk, "chunk_role", "") for chunk in sibling_chunks if getattr(chunk, "chunk_role", "")) or "-"
        shop_name = getattr(parent, "shop_name", None) or getattr(parent, "parent_title", None)
        lines.append(
            f"[{index}] {shop_name} score={float(getattr(parent, 'parent_score', 0.0)):.2f} parent_id={getattr(parent, 'parent_id', '')}"
        )
        business_facts = dict(getattr(parent, "business_facts", {}) or {})
        if business_facts:
            business_bits = ", ".join(
                f"{key}={business_facts.get(key)}"
                for key in ("shop_id", "city", "area", "category", "avg_price", "score", "open_hours")
                if business_facts.get(key) not in (None, "")
            )
            lines.append(f"    business_facts: {business_bits or '-'}")
        parent_context = getattr(parent, "parent_context", None)
        if parent_context is not None:
            lines.append(
                f"    parent_context: {getattr(parent_context, 'chunk_role', '') or getattr(parent_context, 'chunk_id', '')} -> {str(getattr(parent_context, 'text', ''))[:220]}"
            )
        lines.append(f"    matched_roles: {matched_roles}")
        lines.append(f"    sibling_roles: {sibling_roles}")
        score_breakdown = dict(getattr(parent, "score_breakdown", {}) or {})
        if score_breakdown:
            breakdown = ", ".join(f"{key}={value}" for key, value in score_breakdown.items())
            lines.append(f"    score_breakdown: {breakdown}")
        for chunk in [*matched_chunks, *sibling_chunks]:
            text = str(getattr(chunk, "text", "") or "")
            if text:
                lines.append(f"    - {getattr(chunk, 'chunk_role', '')}: {text[:220]}")
    return "\n".join(lines)
