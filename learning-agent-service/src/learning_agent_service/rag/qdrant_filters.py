from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency fallback
    from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue
except ModuleNotFoundError:  # pragma: no cover - lightweight test/runtime fallback
    @dataclass(frozen=True)
    class MatchValue:  # type: ignore[no-redef]
        value: Any

    @dataclass(frozen=True)
    class MatchAny:  # type: ignore[no-redef]
        any: list[Any]

    @dataclass(frozen=True)
    class FieldCondition:  # type: ignore[no-redef]
        key: str
        match: Any | None = None

    @dataclass(frozen=True)
    class Filter:  # type: ignore[no-redef]
        must: list[Any] = field(default_factory=list)

from .models import KnowledgeChunk, RetrievalFilters, RetrievalPlan

_RUNTIME_FILTER_KEYS = {
    "tenant_id",
    "permission_tags",
    "is_active",
}


@dataclass(frozen=True)
class QdrantFilterContext:
    retrieval_filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    tenant_id: Optional[str] = None
    permission_tags: Tuple[str, ...] = ()
    is_active: Optional[bool] = True
    runtime_context: Mapping[str, Any] = field(default_factory=dict)


class QdrantFilterBuilder:
    """将检索过滤条件统一翻译为 Qdrant Filter，同时可复用本地 chunk 匹配。"""

    def build(
        self,
        filters: RetrievalFilters | Mapping[str, Any] | None = None,
        *,
        tenant_id: Any = None,
        permission_tags: Sequence[Any] | None = None,
        is_active: Optional[bool] = True,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> Filter | None:
        context = self._build_context(
            filters,
            tenant_id=tenant_id,
            permission_tags=permission_tags,
            is_active=is_active,
            runtime_context=runtime_context,
        )
        clauses = self._build_clauses(context)
        if not clauses:
            return None
        return Filter(must=clauses)

    def build_for_plan(
        self,
        plan: RetrievalPlan,
        *,
        tenant_id: Any = None,
        permission_tags: Sequence[Any] | None = None,
        is_active: Optional[bool] = True,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> Filter | None:
        return self.build(
            plan.retrieval_filters,
            tenant_id=tenant_id,
            permission_tags=permission_tags,
            is_active=is_active,
            runtime_context=runtime_context or self._plan_runtime_context(plan),
        )

    def matches_chunk(
        self,
        chunk: KnowledgeChunk,
        filters: RetrievalFilters | Mapping[str, Any] | None = None,
        *,
        tenant_id: Any = None,
        permission_tags: Sequence[Any] | None = None,
        is_active: Optional[bool] = True,
        runtime_context: Mapping[str, Any] | None = None,
        ) -> bool:
        context = self._build_context(
            filters,
            tenant_id=tenant_id,
            permission_tags=permission_tags,
            is_active=is_active,
            runtime_context=runtime_context,
        )
        return self._chunk_matches(chunk, context)

    def matches_plan(self, chunk: KnowledgeChunk, plan: RetrievalPlan) -> bool:
        return self.matches_chunk(chunk, plan.retrieval_filters, runtime_context=self._plan_runtime_context(plan))

    def matches_visibility(
        self,
        chunk: KnowledgeChunk,
        filters: RetrievalFilters | Mapping[str, Any] | None = None,
        *,
        tenant_id: Any = None,
        permission_tags: Sequence[Any] | None = None,
        is_active: Optional[bool] = True,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> bool:
        context = self._build_context(
            filters,
            tenant_id=tenant_id,
            permission_tags=permission_tags,
            is_active=is_active,
            runtime_context=runtime_context,
        )
        return self._chunk_matches_visibility(chunk, context)

    def _plan_runtime_context(self, plan: RetrievalPlan) -> Mapping[str, Any]:
        runtime = dict(plan.retrieval_filters.extra)
        for key in _RUNTIME_FILTER_KEYS:
            if key in plan.extra and key not in runtime:
                runtime[key] = plan.extra[key]
        return runtime

    def _build_context(
        self,
        filters: RetrievalFilters | Mapping[str, Any] | None,
        *,
        tenant_id: Any,
        permission_tags: Sequence[Any] | None,
        is_active: Optional[bool],
        runtime_context: Mapping[str, Any] | None,
    ) -> QdrantFilterContext:
        normalized_filters = self._normalize_filters(filters)
        runtime = dict(runtime_context or {})
        merged_runtime = dict(normalized_filters.extra)
        merged_runtime.update(runtime)

        resolved_tenant = self._normalize_single(
            tenant_id if tenant_id is not None else self._first_present(merged_runtime, "tenant_id", "tenant", "workspace_id", "org_id", "organization_id")
        )
        resolved_permissions = self._normalize_values(
            permission_tags if permission_tags is not None else self._first_present(merged_runtime, "permission_tags", "permissions", "permission", "roles", "scopes")
        )
        resolved_active = self._normalize_bool(
            is_active if is_active is not None else self._first_present(merged_runtime, "is_active", "active")
        )
        return QdrantFilterContext(
            retrieval_filters=normalized_filters,
            tenant_id=resolved_tenant,
            permission_tags=resolved_permissions,
            is_active=resolved_active if resolved_active is not None else True,
            runtime_context=merged_runtime,
        )

    def _build_clauses(self, context: QdrantFilterContext) -> list[FieldCondition]:
        clauses: list[FieldCondition] = []
        filters = context.retrieval_filters

        for key, values in filters.as_dict().items():
            if not values:
                continue
            clauses.append(self._build_field_condition(key, values))

        if context.tenant_id:
            clauses.append(FieldCondition(key="tenant_id", match=MatchValue(value=context.tenant_id)))
        if context.permission_tags:
            clauses.append(FieldCondition(key="permission_tags", match=MatchAny(any=list(context.permission_tags))))
        if context.is_active is not None:
            clauses.append(FieldCondition(key="is_active", match=MatchValue(value=bool(context.is_active))))

        for key, value in context.runtime_context.items():
            if key in _RUNTIME_FILTER_KEYS:
                continue
            if value is None or value == "":
                continue
            clauses.append(self._build_field_condition(key, self._normalize_values(value)))

        return clauses

    def _chunk_matches(self, chunk: KnowledgeChunk, context: QdrantFilterContext) -> bool:
        if not self._chunk_matches_visibility(chunk, context):
            return False

        for key, values in context.retrieval_filters.as_dict().items():
            if not values:
                continue
            if not self._value_matches(_metadata_value_for_key(chunk, key), values):
                return False

        for key, value in context.runtime_context.items():
            if key in _RUNTIME_FILTER_KEYS:
                continue
            if value is None or value == "":
                continue
            if not self._value_matches(_metadata_value_for_key(chunk, key), self._normalize_values(value)):
                return False
        return True

    def _chunk_matches_visibility(self, chunk: KnowledgeChunk, context: QdrantFilterContext) -> bool:
        if context.tenant_id:
            if self._normalize_single(_metadata_value_for_key(chunk, "tenant_id")) != context.tenant_id:
                return False
        if context.permission_tags:
            if not self._permission_intersection(chunk, context.permission_tags):
                return False
        if context.is_active is not None:
            chunk_active = self._normalize_bool(_metadata_value_for_key(chunk, "is_active"))
            if chunk_active is None:
                chunk_active = True
            if chunk_active is not bool(context.is_active):
                return False
        return True

    def _build_field_condition(self, key: str, values: Tuple[str, ...]) -> FieldCondition:
        normalized = tuple(value for value in values if value)
        if key == "is_active" and normalized:
            bool_value = self._normalize_bool(normalized[0])
            return FieldCondition(key=key, match=MatchValue(value=bool(bool_value)))
        if len(normalized) <= 1:
            return FieldCondition(key=key, match=MatchValue(value=normalized[0] if normalized else ""))
        return FieldCondition(key=key, match=MatchAny(any=list(normalized)))

    def _normalize_filters(self, filters: RetrievalFilters | Mapping[str, Any] | None) -> RetrievalFilters:
        if filters is None:
            return RetrievalFilters()
        if isinstance(filters, RetrievalFilters):
            return filters
        if not isinstance(filters, Mapping):
            return RetrievalFilters()

        def coerce(value: Any) -> Tuple[str, ...]:
            return self._normalize_values(value)

        extra = dict(filters.get("extra", {}))
        for key, value in filters.items():
            if key in {"category", "subcategory", "difficulty", "source_type", "chunk_type", "version", "tags", "extra"}:
                continue
            if value is None or value == "":
                continue
            extra[key] = value

        return RetrievalFilters(
            category=coerce(filters.get("category")),
            subcategory=coerce(filters.get("subcategory")),
            difficulty=coerce(filters.get("difficulty")),
            source_type=coerce(filters.get("source_type")),
            chunk_type=coerce(filters.get("chunk_type")),
            version=coerce(filters.get("version")),
            tags=coerce(filters.get("tags")),
            extra=extra,
        )

    @staticmethod
    def _normalize_values(value: Any) -> Tuple[str, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Mapping):
            return tuple(str(item) for item in value.values() if item is not None and item != "")
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value if item is not None and item != "")
        return (str(value),)

    @staticmethod
    def _normalize_single(value: Any) -> Optional[str]:
        values = QdrantFilterBuilder._normalize_values(value)
        return values[0] if values else None

    @staticmethod
    def _normalize_bool(value: Any) -> Optional[bool]:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return bool(value)

    @staticmethod
    def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in mapping and mapping.get(key) not in (None, ""):
                return mapping.get(key)
        return None

    @staticmethod
    def _permission_intersection(chunk: KnowledgeChunk, expected_tags: Tuple[str, ...]) -> bool:
        actual_tags = QdrantFilterBuilder._normalize_values(_metadata_value_for_key(chunk, "permission_tags"))
        if not actual_tags:
            actual_tags = QdrantFilterBuilder._normalize_values(chunk.tags)
        if not actual_tags:
            return False
        expected = {tag.strip().lower() for tag in expected_tags if tag}
        actual = {tag.strip().lower() for tag in actual_tags if tag}
        return bool(expected & actual)

    @staticmethod
    def _value_matches(actual: Any, expected: Sequence[str]) -> bool:
        expected_values = {str(value).strip().lower() for value in expected if value}
        if not expected_values:
            return True
        actual_values = QdrantFilterBuilder._normalize_values(actual)
        if not actual_values:
            return False
        return any(value.strip().lower() in expected_values for value in actual_values)


def _metadata_value_for_key(chunk: KnowledgeChunk, key: str) -> Any:
    if key == "category":
        return chunk.category
    if key == "subcategory":
        return chunk.subcategory
    if key == "difficulty":
        return chunk.difficulty
    if key == "source_type":
        return chunk.source_type
    if key == "chunk_type":
        return chunk.chunk_type
    if key == "version":
        return chunk.version
    if key == "tags":
        return chunk.tags
    if key == "tenant_id":
        return chunk.metadata.get("tenant_id")
    if key == "permission_tags":
        return chunk.metadata.get("permission_tags") or chunk.metadata.get("permissions")
    if key == "is_active":
        return chunk.metadata.get("is_active")
    return chunk.metadata.get(key)
