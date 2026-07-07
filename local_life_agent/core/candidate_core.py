"""DEPRECATED_COMPAT: candidate 解析兼容壳。

Canonical path 优先走 target/candidate_resolver 与相关 target 业务层。
Phase 1 冻结这里的调用面，后续再逐步迁移到 canonical path。
"""

from __future__ import annotations

from typing import Any

from ..domain.schemas import ComparisonTargetResolution, ComparisonTurnArtifact
from ..target.candidate_resolver import CandidateResolver
from ..planning.goal.goal_draft import build_candidate_spec


def _unwrap_resolve_shop_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict) and "status" in data:
        return data
    return raw


class CandidateCore:
    def __init__(self, resolver: CandidateResolver | None = None) -> None:
        self._resolver: Any = resolver

    def build_candidate_retrieval_spec(self, *args: Any, **kwargs: Any) -> Any:
        """Build a candidate retrieval spec without executing any DB/tool call."""
        return build_candidate_spec(*args, **kwargs)

    def execute_candidate_retrieval_spec(self, *args: Any, **kwargs: Any) -> Any:
        """Execute a previously built candidate retrieval spec."""
        return self._get_resolver().resolve(*args, **kwargs)

    def resolve(self, *args: Any, **kwargs: Any) -> Any:
        return self.execute_candidate_retrieval_spec(*args, **kwargs)

    def resolve_explicit(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_resolver().resolve_explicit(*args, **kwargs)

    def resolve_context(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_resolver().resolve_context(*args, **kwargs)

    def resolve_mixed(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_resolver().resolve_mixed(*args, **kwargs)

    def resolve_discovery(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_resolver().resolve_discovery(*args, **kwargs)

    def build_comparison_turn_artifact(
        self,
        *,
        text: str,
        session_state: dict | Any | None,
        semantic_frame: dict | Any | None,
        comparison_target_resolution: dict[str, Any] | ComparisonTargetResolution | None = None,
        comparison_targets: list[dict[str, Any]] | None = None,
        pending_clarification: dict[str, Any] | None = None,
        comparison_result: dict[str, Any] | None = None,
        source: str = "comparison_context",
        provenance: str = "semantic_frame",
    ) -> ComparisonTurnArtifact:
        from ..target.clarification import build_pending_clarification
        from ..target.reference_resolver import resolve_comparison_targets

        if comparison_target_resolution is None:
            comparison_target_resolution = resolve_comparison_targets(text, session_state, semantic_frame)
        comparison_target_resolution_data: Any = comparison_target_resolution
        model_dump = getattr(comparison_target_resolution_data, "model_dump", None)
        if callable(model_dump):
            comparison_target_resolution_data = model_dump()
        resolution_dict = dict(comparison_target_resolution_data or {})

        normalized_targets: list[dict[str, Any]] = []
        for item in comparison_targets or resolution_dict.get("targets", []) or []:
            item_dict = item if isinstance(item, dict) else {}
            shop: Any = item_dict.get("resolved_shop") or item_dict.get("shop") or item_dict
            if hasattr(shop, "model_dump"):
                shop = shop.model_dump()
            shop_dict = dict(shop or {})
            shop_id = str(shop_dict.get("shop_id", "") or "").strip()
            shop_name = str(shop_dict.get("shop_name", "") or "").strip()
            if shop_id or shop_name:
                normalized_targets.append({"shop_id": shop_id, "shop_name": shop_name})

        pending_targets = list(normalized_targets)
        unresolved_targets = list(resolution_dict.get("unresolved_targets", []) or [])
        explicit_candidates: list[dict[str, Any]] = []
        resolved_explicit_targets: list[dict[str, Any]] = []
        import re

        raw_text = str(text or "")
        for match in re.finditer(r"[和与](.{1,20}?)(?:比|对比)", raw_text):
            query = str(match.group(1) or "").strip(" ，,。?？!！")
            if not query or query in {"第一家", "第二家", "第三家", "第一个", "第二个", "第三个"}:
                continue
            if any(
                str(existing.get("query", "") or existing.get("source_ref", "") or "").strip() == query
                for existing in unresolved_targets
            ):
                continue
            unresolved_targets.append({"reference": "explicit", "query": query, "source_ref": query})
        if unresolved_targets:
            from ..engine import graph_builder as _graph_builder

            for unresolved in unresolved_targets:
                unresolved_dict = unresolved if isinstance(unresolved, dict) else {}
                if str(unresolved_dict.get("reference", "") or "").strip() != "explicit":
                    continue
                query = str(unresolved_dict.get("query", "") or unresolved_dict.get("source_ref", "") or "").strip()
                if not query:
                    continue
                try:
                    resolved = _unwrap_resolve_shop_result(_graph_builder.resolve_shop(query, location={}))
                except Exception:
                    resolved = {}
                resolved_dict: dict[str, Any] = resolved if isinstance(resolved, dict) else {}
                status = str(resolved_dict.get("status", "") or "").upper()
                shop_id = ""
                shop_name = ""
                if status == "AMBIGUOUS":
                    for candidate in resolved_dict.get("candidates", []) or []:
                        candidate_dict = candidate if isinstance(candidate, dict) else {}
                        candidate_shop: Any = candidate_dict.get("shop") or candidate_dict
                        candidate_dump = getattr(candidate_shop, "model_dump", None)
                        if callable(candidate_dump):
                            candidate_shop = candidate_dump()
                        candidate_shop_dict = dict(candidate_shop or {})
                        shop_id = str(candidate_shop_dict.get("shop_id", "") or "").strip()
                        shop_name = str(candidate_shop_dict.get("shop_name", "") or "").strip()
                        if shop_id or shop_name:
                            candidate_payload = {"shop_id": shop_id, "shop_name": shop_name}
                            if not any(
                                str(existing.get("shop_id", "") or "").strip() == shop_id
                                or str(existing.get("shop_name", "") or "").strip() == shop_name
                                for existing in explicit_candidates
                            ):
                                explicit_candidates.append(candidate_payload)
                elif status == "RESOLVED":
                    shop = resolved_dict.get("shop") or resolved_dict.get("resolved_shop") or {}
                    shop_dump = getattr(shop, "model_dump", None)
                    if callable(shop_dump):
                        shop = shop_dump()
                    shop_dict = dict(shop or {})
                    shop_id = str(shop_dict.get("shop_id", "") or "").strip()
                    shop_name = str(shop_dict.get("shop_name", "") or "").strip()
                if (shop_id or shop_name) and not any(
                    str(existing.get("shop_id", "") or "").strip() == shop_id
                    or str(existing.get("shop_name", "") or "").strip() == shop_name
                    for existing in resolved_explicit_targets
                ):
                    resolved_explicit_targets.append({"shop_id": shop_id, "shop_name": shop_name})

        if resolved_explicit_targets:
            for item in resolved_explicit_targets:
                if not any(
                    str(existing.get("shop_id", "") or "").strip() == str(item.get("shop_id", "") or "").strip()
                    or str(existing.get("shop_name", "") or "").strip() == str(item.get("shop_name", "") or "").strip()
                    for existing in pending_targets
                ):
                    pending_targets.append(item)

        pending: Any = pending_clarification
        if pending is None:
            resolution_status = str(resolution_dict.get("status", "") or "").upper()
            pending_needed = resolution_status in {"NEED_CLARIFICATION", "NOT_FOUND", "TOO_MANY"} or (
                resolution_status == "PARTIAL" and len(pending_targets) < 2 and not resolved_explicit_targets
            )
            if pending_needed:
                if isinstance(semantic_frame, dict):
                    original_task_type_raw = semantic_frame.get("task_type", "") or "comparison"
                else:
                    original_task_type_raw = getattr(semantic_frame, "task_type", "") or "comparison"
                original_task_type = str(getattr(original_task_type_raw, "value", original_task_type_raw) or "comparison")
                pending = build_pending_clarification(
                    original_text=text,
                    original_semantic_frame=semantic_frame or {},
                    original_task_type=original_task_type,
                    candidate_targets=explicit_candidates or pending_targets,
                    reason=str(resolution_dict.get("reason", "") or "comparison_targets_need_clarification"),
                    source_node="candidate_core",
                    expected_reply_type="shop_selection",
                    already_resolved_targets=normalized_targets,
                ).model_dump()
        pending_dump = getattr(pending, "model_dump", None)
        if callable(pending_dump):
            pending = pending_dump()

        comparison_turn_targets = list(pending_targets)
        if not comparison_turn_targets:
            comparison_turn_targets = list(normalized_targets)

        return ComparisonTurnArtifact(
            comparison_targets=comparison_turn_targets,
            comparison_target_resolution=resolution_dict,
            pending_clarification=pending,
            comparison_result=comparison_result,
            displayed_items=[],
            source=source,
            provenance=provenance,
        )

    def _get_resolver(self) -> Any:
        if self._resolver is None:
            from ..engine import graph_builder as gb
            from ..target.candidate_resolver import CandidateResolver as DefaultCandidateResolver

            graph_builder_resolver = getattr(gb, "CandidateResolver", None)
            if callable(graph_builder_resolver) and graph_builder_resolver is not DefaultCandidateResolver:
                self._resolver = graph_builder_resolver()
            else:
                self._resolver = DefaultCandidateResolver()
        return self._resolver
