from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from learning_agent_service.domain.memory import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.memory.gates import MemoryVectorizationGate, MemoryVectorizationGateDecision

try:  # pragma: no cover - optional runtime dependency
    from qdrant_client.http.models import (
        BoolIndexParams,
        DatetimeIndexParams,
        Distance,
        FieldCondition,
        Filter,
        FloatIndexParams,
        IntegerIndexParams,
        KeywordIndexParams,
        MatchAny,
        MatchValue,
        PayloadSchemaType,
        PointIdsList,
        PointStruct,
        TextIndexParams,
        UuidIndexParams,
        VectorParams,
    )
except Exception:  # pragma: no cover - import-tolerant fallback
    BoolIndexParams = DatetimeIndexParams = Distance = FieldCondition = Filter = FloatIndexParams = IntegerIndexParams = KeywordIndexParams = MatchAny = MatchValue = PayloadSchemaType = PointIdsList = PointStruct = TextIndexParams = UuidIndexParams = VectorParams = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if token]


def _embed_text(text: str, vector_size: int) -> List[float]:
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * vector_size
    vector = [0.0] * vector_size
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % vector_size
        vector[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    total = 0.0
    for index, value in enumerate(left):
        if index >= len(right):
            break
        total += value * right[index]
    return total


def _record_text(record: MemoryRecord) -> str:
    content = record.content
    if isinstance(content, Mapping):
        content_text = " ".join(f"{key}:{value}" for key, value in content.items())
    else:
        content_text = str(content)
    return " ".join(
        [
            record.summary or "",
            content_text,
            " ".join(record.tags),
            " ".join(record.entities),
            record.type.value,
            record.scope.value,
            record.status.value,
        ]
    )


def _normalize_point_id(point_id: Any) -> Any:
    if point_id is None:
        return ""
    point_id_text = str(point_id).strip()
    if not point_id_text:
        return ""
    try:
        return str(uuid.UUID(point_id_text))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"learning-agent-service:qdrant:{point_id_text}"))


def _payload_field(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _json_utc(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _payload_from_record(record: MemoryRecord) -> Dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "user_id": record.user_id,
        "session_id": record.session_id,
        "project_id": record.project_id,
        "memory_type": _payload_field(record.type),
        "scope": _payload_field(record.scope),
        "status": _payload_field(record.status),
        "is_active": bool(record.is_active),
        "should_vectorize": bool(record.should_vectorize),
        "normalized_key": record.normalized_key,
        "topic": record.topic,
        "summary": record.summary,
        "tags": list(record.tags or []),
        "entities": list(record.entities or []),
        "confidence": float(record.confidence or 0.0),
        "importance": float(record.importance or 0.0),
        "stability": float(record.stability or 0.0),
        "sensitivity": _payload_field(record.sensitivity),
        "source": _payload_field(record.source),
        "source_turn_id": record.source_turn_id,
        "source_session_id": record.source_session_id,
        "created_at": _json_utc(record.created_at),
        "updated_at": _json_utc(record.updated_at),
        "effective_from": _json_utc(record.effective_from),
        "effective_to": _json_utc(record.effective_to),
        "valid_until": _json_utc(record.valid_until),
        "schema_version": record.schema_version,
    }


def _status_is_active(status: Any) -> bool:
    status_value = status.value if hasattr(status, "value") else str(status or "")
    return status_value in {"active", "confirmed"}


def _scope_is_long_term(scope: Any) -> bool:
    scope_value = scope.value if hasattr(scope, "value") else str(scope or "")
    return scope_value in {"user", "project", "global"}


def _payload_is_searchable(payload: Mapping[str, Any]) -> bool:
    if not _status_is_active(payload.get("status")):
        return False
    if "is_active" in payload and not bool(payload.get("is_active")):
        return False
    if "should_vectorize" in payload and not bool(payload.get("should_vectorize")):
        return False
    if not _scope_is_long_term(payload.get("scope")):
        return False
    if float(payload.get("importance") or 0.0) < 0.6:
        return False
    if float(payload.get("stability") or 0.0) < 0.6:
        return False
    memory_type = str(payload.get("memory_type") or payload.get("type") or "").strip().lower()
    if memory_type not in {"semantic", "episodic", "procedural"}:
        return False
    source_value = str(payload.get("source") or "").strip().lower()
    fact_type = str(payload.get("fact_type") or payload.get("memory_type") or "").strip().lower()
    summary = " ".join(
        [
            str(payload.get("summary") or ""),
            str(payload.get("topic") or ""),
            " ".join(str(item) for item in payload.get("tags") or []),
        ]
    ).lower()
    if source_value == "system_event" and fact_type in {"session_fact", "clarification_event", "missing_slots"}:
        return False
    if any(marker in summary for marker in ("问题还不够具体", "请补充", "继续展开", "需要更具体")):
        return False
    return True


def _normalize_memory_types(memory_types: Optional[Sequence[Any]]) -> Optional[list[str]]:
    if not memory_types:
        return None
    normalized: list[str] = []
    for memory_type in memory_types:
        value = memory_type.value if hasattr(memory_type, "value") else str(memory_type or "")
        value = value.strip().lower()
        if value:
            normalized.append(value)
    return normalized or None


def _build_filter(user_id: str, memory_types: Optional[Sequence[Any]] = None) -> Any:
    if Filter is None or FieldCondition is None or MatchValue is None or MatchAny is None:
        return None
    must = [
        FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        FieldCondition(key="should_vectorize", match=MatchValue(value=True)),
        FieldCondition(key="is_active", match=MatchValue(value=True)),
        FieldCondition(key="status", match=MatchAny(any=["active", "confirmed"])),
    ]
    normalized_types = _normalize_memory_types(memory_types)
    if normalized_types is None:
        must.append(FieldCondition(key="memory_type", match=MatchAny(any=["semantic", "episodic", "procedural"])))
    else:
        must.append(FieldCondition(key="memory_type", match=MatchAny(any=normalized_types)))
    return Filter(
        must=must,
        must_not=[
            FieldCondition(key="scope", match=MatchAny(any=["turn", "session"])),
        ],
    )


def _collection_vectors(collection_info: Any) -> Any:
    config = getattr(collection_info, "config", None)
    params = getattr(config, "params", None) if config is not None else None
    return getattr(params, "vectors", None) if params is not None else None


def _distance_matches(expected: Any, actual: Any) -> bool:
    expected_value = expected.value if hasattr(expected, "value") else str(expected or "").lower()
    actual_value = actual.value if hasattr(actual, "value") else str(actual or "").lower()
    return expected_value == actual_value


def _distance_value(distance: Any) -> Any:
    if Distance is None:
        return distance
    if hasattr(distance, "value"):
        return distance
    if isinstance(distance, str):
        candidate = distance.strip().upper()
        try:
            return Distance[candidate]
        except Exception:
            pass
    return Distance.COSINE


def _create_payload_index(client: Any, collection_name: str, field_name: str, field_schema: Any) -> None:
    create_payload_index = getattr(client, "create_payload_index", None)
    if not callable(create_payload_index):
        return
    try:
        create_payload_index(collection_name=collection_name, field_name=field_name, field_schema=field_schema)
    except TypeError:
        try:
            create_payload_index(collection_name, field_name, field_schema)
        except Exception:
            return
    except Exception:
        return


@dataclass
class QdrantLongTermMemoryIndex:
    """Qdrant-backed semantic index for active long-term memory."""

    client: Any
    collection_name: str
    vector_size: Optional[int] = None
    vector_name: str = "embedding"
    distance: Any = field(default_factory=lambda: Distance.COSINE if Distance is not None else "cosine")
    embedding_adapter: Any = None
    vectorization_gate: MemoryVectorizationGate = field(default_factory=MemoryVectorizationGate)
    fallback_points: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_error: Optional[str] = None
    last_operation: Optional[str] = None
    _collection_ready: bool = field(default=False, init=False, repr=False)

    def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        if self.vector_size is None:
            raise RuntimeError(
                f"Memory collection {self.collection_name} requires an explicit vector_size; "
                f"refusing to fall back to 64"
            )
        create_collection = getattr(self.client, "create_collection", None)
        if not callable(create_collection):
            self._collection_ready = True
            return
        exists = self._collection_exists()
        if exists:
            self._validate_collection_shape()
            self._ensure_payload_indexes()
            self._collection_ready = True
            return
        if VectorParams is None:
            self._collection_ready = True
            return
        vectors_config = {self.vector_name: VectorParams(size=int(self.vector_size), distance=_distance_value(self.distance))}
        create_collection(collection_name=self.collection_name, vectors_config=vectors_config)
        self._ensure_payload_indexes()
        self._collection_ready = True

    def upsert(self, record: MemoryRecord) -> str:
        self.last_operation = "upsert"
        self.last_error = None
        vector_decision = self.vectorization_gate.should_vectorize(record)
        point_id = _normalize_point_id(record.vector_id or record.memory_id)
        if not vector_decision.allowed or not point_id:
            return str(point_id or "")
        vector = self._embed(record, _record_text(record))
        self._validate_embedding(vector)
        payload = _payload_from_record(record)
        self.fallback_points[str(point_id)] = {"vector": vector, "payload": payload}
        upsert = getattr(self.client, "upsert", None)
        if callable(upsert):
            self.ensure_collection()
            point = (
                PointStruct(id=point_id, vector={self.vector_name: vector}, payload=payload)
                if PointStruct is not None
                else {"id": point_id, "vector": {self.vector_name: vector}, "payload": payload}
            )
            try:
                try:
                    upsert(collection_name=self.collection_name, points=[point], wait=False)
                except TypeError:
                    upsert(collection_name=self.collection_name, points=[point])
            except Exception as exc:
                self.last_error = type(exc).__name__
        return str(point_id)

    def delete(self, point_id: str) -> None:
        self.delete_many([point_id])

    def delete_many(self, point_ids: Sequence[str]) -> None:
        self.last_operation = "delete"
        self.last_error = None
        ids = [point_id for point_id in point_ids if point_id]
        if not ids:
            return
        for point_id in ids:
            self.fallback_points.pop(_normalize_point_id(point_id), None)
        delete = getattr(self.client, "delete", None)
        if callable(delete):
            try:
                selector = PointIdsList(points=[_normalize_point_id(point_id) for point_id in ids]) if PointIdsList is not None else [_normalize_point_id(point_id) for point_id in ids]
                delete(collection_name=self.collection_name, points_selector=selector)
            except TypeError:
                try:
                    delete(collection_name=self.collection_name, points=ids)
                except Exception:
                    self.last_error = "delete_failed"
            except Exception:
                self.last_error = "delete_failed"

    def soft_deactivate(self, point_id: str, *, payload: Optional[Mapping[str, Any]] = None) -> None:
        self.last_operation = "soft_deactivate"
        self.last_error = None
        normalized_id = _normalize_point_id(point_id)
        if not normalized_id:
            return
        existing = self.fallback_points.get(normalized_id)
        current_payload = dict(existing.get("payload", {})) if existing else {}
        current_payload.update(
            dict(payload or {})
            | {
                "status": "superseded",
                "is_active": False,
                "effective_to": _utcnow_iso(),
            }
        )
        if existing is not None:
            existing["payload"] = current_payload
        else:
            self.fallback_points[normalized_id] = {
                "vector": self._embed_payload(current_payload.get("summary", "")),
                "payload": current_payload,
            }

        update_payload = getattr(self.client, "set_payload", None)
        if not callable(update_payload):
            update_payload = getattr(self.client, "overwrite_payload", None)
        if callable(update_payload):
            kwargs: Dict[str, Any] = {
                "collection_name": self.collection_name,
                "payload": {
                    "status": "superseded",
                    "is_active": False,
                    "effective_to": current_payload.get("effective_to"),
                },
            }
            selector = PointIdsList(points=[normalized_id]) if PointIdsList is not None else [normalized_id]
            try:
                update_payload(points=selector, **kwargs)
            except TypeError:
                try:
                    update_payload(points_selector=selector, **kwargs)
                except Exception:
                    self.last_error = "soft_deactivate_failed"
            except Exception:
                self.last_error = "soft_deactivate_failed"

    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 10,
        memory_types: Optional[Sequence[Any]] = None,
    ) -> Sequence[MemoryRecord]:
        self.last_operation = "search"
        self.last_error = None
        vector = self._embed_query(query or "")
        if vector is None:
            return []
        query_points = getattr(self.client, "query_points", None)
        if callable(query_points):
            try:
                response = query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    using=self.vector_name,
                    query_filter=_build_filter(user_id, memory_types=memory_types),
                    limit=limit,
                    with_payload=True,
                )
                records = self._points_to_records(
                    self._extract_points(response),
                    user_id=user_id,
                    limit=limit,
                    memory_types=memory_types,
                )
                if records:
                    return records
            except Exception:
                self.last_error = "search_failed"
        search_method = getattr(self.client, "search", None)
        if callable(search_method):
            try:
                response = search_method(
                    collection_name=self.collection_name,
                    query_vector=vector,
                    query_filter=_build_filter(user_id, memory_types=memory_types),
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                records = self._points_to_records(
                    self._extract_points(response),
                    user_id=user_id,
                    limit=limit,
                    memory_types=memory_types,
                )
                if records:
                    return records
            except Exception:
                self.last_error = "search_failed"
        return self._search_fallback(vector=vector, user_id=user_id, limit=limit, memory_types=memory_types)

    def _search_fallback(
        self,
        *,
        vector: Sequence[float],
        user_id: str,
        limit: int,
        memory_types: Optional[Sequence[Any]] = None,
    ) -> Sequence[MemoryRecord]:
        normalized_types = set(_normalize_memory_types(memory_types) or [])
        scored: List[tuple[float, Dict[str, Any]]] = []
        for point in self.fallback_points.values():
            payload = point.get("payload", {})
            if payload.get("user_id") != user_id:
                continue
            if not _payload_is_searchable(payload):
                continue
            if normalized_types and str(payload.get("memory_type") or "").strip().lower() not in normalized_types:
                continue
            score = _cosine(vector, point.get("vector", ()))
            scored.append((score, payload))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [self._payload_to_record(payload) for _, payload in scored[:limit]]

    def _collection_exists(self) -> bool:
        collection_exists = getattr(self.client, "collection_exists", None)
        if callable(collection_exists):
            try:
                return bool(collection_exists(self.collection_name))
            except Exception:
                return False
        get_collection = getattr(self.client, "get_collection", None)
        if callable(get_collection):
            try:
                get_collection(self.collection_name)
                return True
            except Exception:
                return False
        return False

    def _validate_collection_shape(self) -> None:
        if self.vector_size is None:
            raise RuntimeError(
                f"Memory collection {self.collection_name} requires explicit vector_size"
            )
        get_collection = getattr(self.client, "get_collection", None)
        if not callable(get_collection):
            return
        collection_info = get_collection(self.collection_name)
        vectors = _collection_vectors(collection_info)
        if vectors is None:
            raise RuntimeError(
                "Memory Qdrant collection shape mismatch:\n"
                f"collection={self.collection_name}\n"
                f"vector_name={self.vector_name}\n"
                f"expected_vector_size={self.vector_size}\n"
                "actual_vector_size=unknown\n"
                f"action=run memory reindex command with --drop-existing --expected-old-vector-size 64"
            )
        if not isinstance(vectors, Mapping):
            raise RuntimeError(
                "Memory Qdrant collection shape mismatch:\n"
                f"collection={self.collection_name}\n"
                f"vector_name={self.vector_name}\n"
                f"expected_vector_size={self.vector_size}\n"
                "actual_vector_size=unknown\n"
                f"action=run memory reindex command with --drop-existing --expected-old-vector-size 64"
            )
        vector_params = vectors.get(self.vector_name)
        if vector_params is None:
            raise RuntimeError(
                "Memory Qdrant collection shape mismatch:\n"
                f"collection={self.collection_name}\n"
                f"vector_name={self.vector_name}\n"
                f"expected_vector_size={self.vector_size}\n"
                "actual_vector_size=unknown\n"
                f"action=run memory reindex command with --drop-existing --expected-old-vector-size 64"
            )
        size = getattr(vector_params, "size", None)
        distance = getattr(vector_params, "distance", None)
        if size is not None and int(size) != int(self.vector_size):
            raise RuntimeError(
                "Memory Qdrant collection shape mismatch:\n"
                f"collection={self.collection_name}\n"
                f"vector_name={self.vector_name}\n"
                f"expected_vector_size={self.vector_size}\n"
                f"actual_vector_size={size}\n"
                f"action=run memory reindex command with --drop-existing --expected-old-vector-size 64"
            )
        if distance is not None and not _distance_matches(self.distance, distance):
            raise RuntimeError(
                "Memory Qdrant collection shape mismatch:\n"
                f"collection={self.collection_name}\n"
                f"vector_name={self.vector_name}\n"
                f"expected_distance={_distance_value(self.distance)}\n"
                f"actual_distance={distance}\n"
            )

    def _ensure_payload_indexes(self) -> None:
        fields = {
            "memory_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "user_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "session_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "project_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "memory_type": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "scope": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "status": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "is_active": PayloadSchemaType.BOOL if PayloadSchemaType is not None else None,
            "should_vectorize": PayloadSchemaType.BOOL if PayloadSchemaType is not None else None,
            "normalized_key": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "topic": PayloadSchemaType.TEXT if PayloadSchemaType is not None else None,
            "source": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "source_turn_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "source_session_id": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
            "created_at": PayloadSchemaType.DATETIME if PayloadSchemaType is not None else None,
            "updated_at": PayloadSchemaType.DATETIME if PayloadSchemaType is not None else None,
            "effective_from": PayloadSchemaType.DATETIME if PayloadSchemaType is not None else None,
            "effective_to": PayloadSchemaType.DATETIME if PayloadSchemaType is not None else None,
            "valid_until": PayloadSchemaType.DATETIME if PayloadSchemaType is not None else None,
            "schema_version": PayloadSchemaType.KEYWORD if PayloadSchemaType is not None else None,
        }
        for field_name, schema in fields.items():
            if schema is None:
                continue
            _create_payload_index(self.client, self.collection_name, field_name, schema)

    def _embed(self, record: MemoryRecord, text: str) -> List[float]:
        vector = self._embed_payload(text)
        if self.embedding_adapter is not None:
            vector = list(self.embedding_adapter.embed(text))
        self._validate_embedding(vector)
        return vector

    def _embed_query(self, text: str) -> Optional[List[float]]:
        if not text and self.embedding_adapter is None and self.vector_size is None:
            return None
        vector = self._embed_payload(text)
        if self.embedding_adapter is not None:
            vector = list(self.embedding_adapter.embed(text))
        self._validate_embedding(vector)
        return vector

    def _embed_payload(self, text: str) -> List[float]:
        if self.vector_size is None:
            raise RuntimeError(
                f"Memory collection {self.collection_name} requires an explicit vector_size before embedding"
            )
        return _embed_text(text or "", int(self.vector_size))

    def _validate_embedding(self, vector: Sequence[float]) -> None:
        if self.vector_size is None:
            raise RuntimeError(
                f"Memory embedding dimension mismatch: expected configured vector_size for collection={self.collection_name}"
            )
        actual = len(vector)
        if actual != int(self.vector_size):
            model = getattr(self.embedding_adapter, "model", None) or getattr(self.embedding_adapter, "default_model", None) or "unknown"
            raise RuntimeError(
                f"Memory embedding dimension mismatch: expected={self.vector_size}, got={actual}, "
                f"model={model}, collection={self.collection_name}"
            )

    @staticmethod
    def _extract_points(response: Any) -> Sequence[Any]:
        if response is None:
            return []
        points = getattr(response, "points", None)
        if points is not None:
            return points
        if isinstance(response, Mapping):
            points = response.get("points")
            if points is not None:
                return points
        return response if isinstance(response, Sequence) else []

    def _points_to_records(
        self,
        points: Any,
        *,
        user_id: str,
        limit: int,
        memory_types: Optional[Sequence[Any]] = None,
    ) -> Sequence[MemoryRecord]:
        normalized_types = set(_normalize_memory_types(memory_types) or [])
        records: List[MemoryRecord] = []
        for point in points or []:
            payload = getattr(point, "payload", None)
            if payload is None and isinstance(point, Mapping):
                payload = point.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if payload.get("user_id") not in {None, user_id}:
                continue
            if not _payload_is_searchable(payload):
                continue
            if normalized_types and str(payload.get("memory_type") or "").strip().lower() not in normalized_types:
                continue
            records.append(self._payload_to_record(payload))
            if len(records) >= limit:
                break
        return records

    @staticmethod
    def _payload_to_record(payload: Mapping[str, Any]) -> MemoryRecord:
        normalized = dict(payload)
        normalized.setdefault("memory_id", str(payload.get("memory_id") or payload.get("id") or ""))
        normalized.setdefault("user_id", str(payload.get("user_id") or ""))
        normalized.setdefault("source_turn_id", str(payload.get("source_turn_id") or ""))
        normalized.setdefault("content", payload.get("content") or {})
        normalized.setdefault("summary", payload.get("summary"))
        normalized.setdefault("tags", list(payload.get("tags") or []))
        normalized.setdefault("entities", list(payload.get("entities") or []))
        normalized.setdefault("type", payload.get("memory_type") or payload.get("type") or "semantic")
        normalized.setdefault("scope", payload.get("scope") or "user")
        normalized.setdefault("status", payload.get("status") or "active")
        normalized.setdefault("normalized_key", payload.get("normalized_key"))
        normalized.setdefault("is_active", bool(payload.get("is_active", True)))
        normalized.setdefault("effective_from", payload.get("effective_from") or _utcnow_iso())
        normalized.setdefault("effective_to", payload.get("effective_to"))
        normalized.setdefault("source_session_id", payload.get("source_session_id"))
        normalized.setdefault("confidence", float(payload.get("confidence") or 0.0))
        normalized.setdefault("importance", float(payload.get("importance") or 0.0))
        normalized.setdefault("stability", float(payload.get("stability") or 0.0))
        normalized.setdefault("should_vectorize", bool(payload.get("should_vectorize", True)))
        normalized.setdefault("valid_until", payload.get("valid_until"))
        normalized.setdefault("project_id", payload.get("project_id"))
        normalized.setdefault("session_id", payload.get("session_id"))
        normalized.setdefault("source", payload.get("source") or "system_event")
        return MemoryRecord.model_validate(normalized)
