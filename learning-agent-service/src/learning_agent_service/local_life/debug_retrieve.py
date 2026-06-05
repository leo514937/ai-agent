from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from learning_agent_service.adapters.java_business import JavaBusinessClient
from learning_agent_service.application.dependencies import OpenAIEmbeddingAdapter
from learning_agent_service.config import get_settings
from learning_agent_service.infrastructure.db.openai_client import build_openai_runtime
from learning_agent_service.infrastructure.db.qdrant import build_qdrant_runtime
from learning_agent_service.local_life.query_rewriter import normalize_query
from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.rag.local_life import LocalLifeParentChildRetriever
from learning_agent_service.rag.local_life import (
    build_arg_parser as _build_retrieval_arg_parser,
)
from learning_agent_service.domain.utils import as_mapping as _as_mapping


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _build_retrieval_arg_parser()
    parser.description = "Debug local life hybrid retrieval and parent-child evidence packs."
    parser.add_argument("--json", action="store_true", help="Print the debug pack as JSON.")
    return parser


def _pack_to_dict(pack: Any) -> dict[str, Any]:
    if is_dataclass(pack):
        return asdict(pack)
    if hasattr(pack, "model_dump"):
        dumped = pack.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return _as_mapping(pack)


def _format_pack(pack: Any, *, decision: Any | None = None) -> str:
    decision_map = _as_mapping(decision)
    lines = [
        f"route: {getattr(pack, 'route', None) or decision_map.get('route') or '-'}",
        f"retrieval_strategy: {getattr(pack, 'retrieval_strategy', '-')}",
        f"total_child_hits: {getattr(pack, 'total_child_hits', 0)}",
    ]
    if getattr(pack, "route_reason", None):
        lines.append(f"route_reason: {pack.route_reason}")
    if decision_map.get("query_tags"):
        lines.append(f"query_tags: {', '.join(decision_map['query_tags'])}")
    parent_evidences = list(getattr(pack, "parent_evidences", []) or [])
    if not parent_evidences:
        lines.append("No evidence found.")
        return "\n".join(lines)

    for index, parent in enumerate(parent_evidences, start=1):
        lines.append(
            f"[{index}] parent_id={parent.parent_id} shop_name={parent.shop_name or parent.parent_title} parent_score={parent.parent_score:.4f}"
        )
        lines.append(f"    matched_roles: {', '.join(chunk.chunk_role for chunk in parent.matched_chunks if chunk.chunk_role) or '-'}")
        lines.append(f"    sibling_roles: {', '.join(chunk.chunk_role for chunk in parent.sibling_chunks if chunk.chunk_role) or '-'}")
        if getattr(parent, "business_facts", None):
            business_facts = _as_mapping(parent.business_facts)
            summary = ", ".join(
                f"{key}={business_facts.get(key)}"
                for key in ("shop_id", "city", "area", "category", "avg_price", "score", "open_hours")
                if business_facts.get(key) not in (None, "")
            )
            lines.append(f"    business facts: {summary or '-'}")
        if getattr(parent, "score_breakdown", None):
            score_breakdown = _as_mapping(parent.score_breakdown)
            lines.append(
                "    score breakdown: "
                + ", ".join(f"{key}={value}" for key, value in score_breakdown.items())
            )
        lines.append("    semantic evidence:")
        for chunk in parent.matched_chunks:
            lines.append(
                f"      - matched {chunk.chunk_role or '-'} score={(chunk.score if chunk.score is not None else 0.0):.4f} text={chunk.text[:180]}"
            )
        for chunk in parent.sibling_chunks:
            lines.append(
                f"      - sibling {chunk.chunk_role or '-'} score={(chunk.score if chunk.score is not None else 0.0):.4f} text={chunk.text[:180]}"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    qdrant_runtime = build_qdrant_runtime(settings.qdrant)
    openai_runtime = build_openai_runtime(settings.openai)
    router = LocalLifeQueryRouter()
    business_client = JavaBusinessClient(settings)
    retriever = LocalLifeParentChildRetriever(
        qdrant_client=qdrant_runtime.client,
        embedding_adapter=OpenAIEmbeddingAdapter(runtime=openai_runtime, model=settings.openai.embedding_model),
        collection_name=args.collection_name,
        vector_name=args.vector_name,
    )

    client_context = {
        "city": args.city,
        "area": args.area,
        "shop_type_id": args.shop_type_id,
    }
    understanding = normalize_query(args.query, client_context=client_context, session_context={})
    slots, _, intent = extract_slots(
        understanding,
        args.query,
        client_context=client_context,
        session_context={},
    )
    decision = router.route(
        args.query,
        slots=slots,
        intent=intent,
        candidate_shop_ids=args.candidate_shop_ids or None,
    )

    candidate_shop_ids = list(args.candidate_shop_ids or [])
    structured_candidates = []
    if decision.use_business_candidates:
        try:
            structured_candidates = business_client.search_candidates(
                query=understanding.semantic_query or understanding.keyword_query or args.query,
                slots=slots,
                limit=getattr(settings, "local_life_candidate_limit", 5),
            )
            candidate_shop_ids = candidate_shop_ids or [shop.id for shop in structured_candidates]
        except Exception:
            structured_candidates = []

    pack = retriever.retrieve_local_life_evidence(
        args.query,
        route=decision.route,
        city=args.city,
        area=args.area,
        category=args.category or slots.category,
        shop_type_id=args.shop_type_id,
        candidate_shop_ids=candidate_shop_ids or None,
        child_top_k=decision.child_top_k,
        parent_top_k=decision.parent_top_k,
        sibling_limit_per_parent=decision.sibling_limit_per_parent,
    )

    if args.json:
        output = {
            "decision": decision.as_dict(),
            "pack": _pack_to_dict(pack),
            "structured_candidates": [candidate.model_dump(mode="json") for candidate in structured_candidates],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(_format_pack(pack, decision=decision))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main(sys.argv[1:]))
