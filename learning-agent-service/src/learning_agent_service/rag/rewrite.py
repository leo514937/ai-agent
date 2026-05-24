from __future__ import annotations

import logging
import json
import time
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Tuple

from .models import RetrievalFilters, RetrievalPlan, coerce_tuple

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_+#.:-]+|[\u4e00-\u9fff]+")
_LOGGER = logging.getLogger(__name__)

INTENT_CHUNK_MAP = {
    "explain": ("concept", "qa", "roadmap"),
    "compare": ("comparison", "qa"),
    "follow_up": ("concept", "comparison", "qa"),
    "summary": ("qa", "concept", "roadmap"),
}

_CATEGORY_HINTS = {
    "java": ("spring", "aop", "bean", "transaction", "boot", "java", "jvm", "并发", "线程池", "锁", "事务"),
    "agent": ("agent", "langgraph", "react", "tool", "memory", "workflow"),
    "rag": ("rag", "retrieval", "embedding", "rerank", "qdrant", "chunk"),
    "redis": ("redis", "缓存", "持久化"),
}

_SOURCE_HINTS = {
    "faq": ("区别", "为什么"),
    "document": ("原理", "概念", "解释", "怎么"),
}


@dataclass(frozen=True)
class QueryRewriteContext:
    raw_query: str
    intent: Optional[str] = None
    resolved_topic: Optional[str] = None
    session_topic: Optional[str] = None
    requested_output_style: Optional[str] = None
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    user_preferences: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)
    intent_confidence: float = 0.0


@dataclass(frozen=True)
class QueryRewriteConfig:
    llm_enabled: bool = False
    short_query_max_chars: int = 6
    low_confidence_threshold: float = 0.5
    llm_retry_limit: int = 1
    llm_model: Optional[str] = None
    llm_temperature: float = 0.0
    hyde_enabled: bool = False
    hyde_model: Optional[str] = None
    hyde_temperature: float = 0.0


class QueryRewriteService:
    def __init__(
        self,
        config: Optional[QueryRewriteConfig] = None,
        *,
        llm_rewriter: Optional[Callable[[QueryRewriteContext, RetrievalPlan, str], Mapping[str, Any]]] = None,
        hyde_rewriter: Optional[Callable[[QueryRewriteContext, RetrievalPlan, str], Mapping[str, Any]]] = None,
    ) -> None:
        self._config = config or QueryRewriteConfig()
        self._llm_rewriter = llm_rewriter
        self._hyde_rewriter = hyde_rewriter

    def build_plan(self, context: QueryRewriteContext) -> RetrievalPlan:
        semantic_query = self._build_semantic_query(context)
        keyword_query = self._build_keyword_query(context, semantic_query)
        preferred_chunk_types = self._preferred_chunk_types(context)
        filters = self._build_filters(context, preferred_chunk_types)
        extra = {
            "raw_query": context.raw_query,
            "rewrite_applied": semantic_query != context.raw_query,
            "resolved_topic": context.resolved_topic,
            "session_topic": context.session_topic,
            "intent": context.intent,
            "requested_output_style": context.requested_output_style,
            "user_preferences": dict(context.user_preferences),
            "base_filters": filters.as_dict() | {"extra": dict(filters.extra)},
            "intent_confidence": context.intent_confidence,
            "rewrite_source": "rule",
            "filter_confidence": 1.0,
            "step_back_query": None,
            "rewritten_queries": [],
            "supplemental_queries": [],
            "metadata_filter_mode": "soft",
        }
        return RetrievalPlan(
            semantic_query=semantic_query,
            keyword_query=keyword_query,
            retrieval_filters=filters,
            preferred_chunk_types=preferred_chunk_types,
            step_back_query=None,
            rewritten_queries=(),
            supplemental_queries=(),
            metadata_filter_mode="soft",
            extra=extra,
        )

    def rewrite_with_llm(self, plan_or_context: RetrievalPlan | QueryRewriteContext, fallback_reason: str = "") -> RetrievalPlan:
        if not self._config.llm_enabled or self._llm_rewriter is None:
            return self._coerce_plan(plan_or_context)

        context, base_plan = self._coerce_context_and_plan(plan_or_context)
        if not self._should_try_llm(context, base_plan, fallback_reason):
            return base_plan

        started_at = time.perf_counter()
        payload = self._llm_rewriter(context, base_plan, fallback_reason)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "rag_query_rewrite_timing elapsed_ms=%.1f source=llm fallback_reason=%s query_chars=%s",
            elapsed_ms,
            fallback_reason or "",
            len(context.raw_query or ""),
        )
        normalized = self._normalize_llm_payload(payload, context, base_plan)
        if normalized is None:
            return base_plan

        semantic_query = normalized.get("semantic_query") or base_plan.semantic_query
        keyword_query = normalized.get("keyword_query") or base_plan.keyword_query
        step_back_query = normalized.get("step_back_query")
        rewritten_queries = tuple(
            str(item)
            for item in normalized.get("rewritten_queries", [])
            if item
        )
        supplemental_queries = self._normalize_queries(
            step_back_query,
            *rewritten_queries,
            base_plan.semantic_query,
            base_plan.keyword_query,
        )
        filter_confidence = float(normalized.get("filter_confidence", 0.0) or 0.0)
        retrieval_filters = self._merge_filters(base_plan.retrieval_filters, normalized.get("retrieval_filters"))
        hard_filter = filter_confidence >= self._config.low_confidence_threshold
        extra = dict(base_plan.extra)
        extra.update(
            {
                "rewrite_source": "llm",
                "rewrite_reason": fallback_reason or "llm_rewrite_triggered",
                "step_back_query": step_back_query,
                "rewritten_queries": list(rewritten_queries),
                "supplemental_queries": list(supplemental_queries),
                "filter_confidence": filter_confidence,
                "metadata_filter_mode": "hard" if hard_filter else "soft",
                "llm_payload": normalized,
            }
        )
        return RetrievalPlan(
            semantic_query=semantic_query,
            keyword_query=keyword_query,
            retrieval_filters=retrieval_filters,
            preferred_chunk_types=base_plan.preferred_chunk_types,
            step_back_query=str(step_back_query or "") or None,
            rewritten_queries=rewritten_queries,
            supplemental_queries=tuple(supplemental_queries),
            metadata_filter_mode="hard" if hard_filter else "soft",
            dense_top_k=base_plan.dense_top_k,
            sparse_top_k=base_plan.sparse_top_k,
            metadata_top_k=base_plan.metadata_top_k,
            rerank_top_k=base_plan.rerank_top_k,
            max_evidence=base_plan.max_evidence,
            extra=extra,
        )

    def build_hyde_payload(
        self,
        plan_or_context: RetrievalPlan | QueryRewriteContext,
        fallback_reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not self._config.hyde_enabled or self._hyde_rewriter is None:
            return None

        context, base_plan = self._coerce_context_and_plan(plan_or_context)
        trigger_reason = self._infer_hyde_trigger_reason(context, base_plan, fallback_reason)
        if not trigger_reason:
            return None

        started_at = time.perf_counter()
        payload = self._hyde_rewriter(context, base_plan, trigger_reason)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        _LOGGER.info(
            "rag_hyde_timing elapsed_ms=%.1f source=llm trigger_reason=%s query_chars=%s",
            elapsed_ms,
            trigger_reason,
            len(context.raw_query or ""),
        )
        normalized = self._normalize_hyde_payload(payload)
        if normalized is None:
            return None

        hyde_passage = str(normalized.get("hyde_passage") or "").strip()
        if not hyde_passage:
            return None

        extra = dict(normalized)
        extra.update(
            {
                "hyde_passage": hyde_passage,
                "hyde_trigger_reason": trigger_reason,
                "hyde_source": "llm",
                "raw_query": context.raw_query,
                "hyde_payload": normalized,
            }
        )
        return extra

    def _coerce_plan(self, plan_or_context: RetrievalPlan | QueryRewriteContext) -> RetrievalPlan:
        if isinstance(plan_or_context, RetrievalPlan):
            return plan_or_context
        return self.build_plan(plan_or_context)

    def _coerce_context_and_plan(self, plan_or_context: RetrievalPlan | QueryRewriteContext) -> tuple[QueryRewriteContext, RetrievalPlan]:
        if isinstance(plan_or_context, QueryRewriteContext):
            plan = self.build_plan(plan_or_context)
            return plan_or_context, plan
        extra = dict(plan_or_context.extra)
        context = QueryRewriteContext(
            raw_query=str(extra.get("raw_query") or plan_or_context.semantic_query or ""),
            intent=extra.get("intent"),
            resolved_topic=extra.get("resolved_topic"),
            session_topic=extra.get("session_topic"),
            requested_output_style=extra.get("requested_output_style"),
            filters=plan_or_context.retrieval_filters,
            user_preferences=dict(extra.get("user_preferences", {})),
            extra=extra,
            intent_confidence=float(extra.get("intent_confidence", 0.0) or 0.0),
        )
        return context, plan_or_context

    def _should_try_llm(self, context: QueryRewriteContext, plan: RetrievalPlan, fallback_reason: str) -> bool:
        if not self._config.llm_enabled:
            return False
        if self._llm_rewriter is None:
            return False
        if fallback_reason == "empty_recall":
            return True
        query = (context.raw_query or "").strip()
        if len(query) <= self._config.short_query_max_chars:
            return True
        if _contains_reference_token(query, query.lower()):
            return True
        if float(context.intent_confidence or 0.0) < self._config.low_confidence_threshold:
            return True
        if self._looks_ambiguous(query):
            return True
        if plan.retrieval_filters.has_constraints() and float(plan.extra.get("filter_confidence", 1.0) or 0.0) < self._config.low_confidence_threshold:
            return True
        return False

    def _infer_hyde_trigger_reason(self, context: QueryRewriteContext, plan: RetrievalPlan, fallback_reason: str) -> str:
        if not self._config.hyde_enabled:
            return ""
        if self._hyde_rewriter is None:
            return ""
        if fallback_reason == "empty_recall":
            return fallback_reason

        reasons = []
        query = (context.raw_query or "").strip()
        if not query:
            return ""
        if len(query) <= self._config.short_query_max_chars:
            reasons.append("short_query")
        if _contains_reference_token(query, query.lower()):
            reasons.append("reference_query")
        if float(context.intent_confidence or 0.0) < self._config.low_confidence_threshold:
            reasons.append("low_intent_confidence")
        if self._looks_ambiguous(query):
            reasons.append("ambiguous_query")
        if plan.retrieval_filters.has_constraints() and float(plan.extra.get("filter_confidence", 1.0) or 0.0) < self._config.low_confidence_threshold:
            reasons.append("low_filter_confidence")
        return ";".join(dict.fromkeys(reasons))

    def _normalize_llm_payload(
        self,
        payload: Mapping[str, Any] | str | None,
        context: QueryRewriteContext,
        plan: RetrievalPlan,
    ) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return None
        else:
            data = dict(payload)
        if not isinstance(data, dict):
            return None
        return {
            "semantic_query": str(data.get("semantic_query") or ""),
            "keyword_query": str(data.get("keyword_query") or ""),
            "rewritten_queries": list(data.get("rewritten_queries") or []),
            "step_back_query": str(data.get("step_back_query") or ""),
            "retrieval_filters": data.get("retrieval_filters") or {},
            "filter_confidence": float(data.get("filter_confidence", 0.0) or 0.0),
            "raw_query": context.raw_query,
            "base_plan": plan.extra,
        }

    def _normalize_hyde_payload(self, payload: Mapping[str, Any] | str | None) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"hyde_passage": payload}
        else:
            data = dict(payload)
        if not isinstance(data, dict):
            return None
        hyde_passage = str(data.get("hyde_passage") or data.get("passage") or "").strip()
        if not hyde_passage:
            return None
        hyde_keywords = data.get("hyde_keywords") or data.get("keywords") or []
        if isinstance(hyde_keywords, str):
            hyde_keywords = [hyde_keywords]
        elif not isinstance(hyde_keywords, list):
            hyde_keywords = list(hyde_keywords) if hyde_keywords else []
        return {
            "hyde_passage": hyde_passage,
            "hyde_title": str(data.get("hyde_title") or ""),
            "hyde_keywords": [str(item) for item in hyde_keywords if item],
            "retrieval_filters": data.get("retrieval_filters") or {},
            "filter_confidence": float(data.get("filter_confidence", 0.0) or 0.0),
        }

    def _merge_filters(self, base_filters: RetrievalFilters, raw_filters: Any) -> RetrievalFilters:
        if not isinstance(raw_filters, Mapping):
            return base_filters

        def coerce(value: Any) -> Tuple[str, ...]:
            if not value:
                return ()
            if isinstance(value, str):
                return (value,)
            return tuple(str(item) for item in value if item)

        extra = dict(base_filters.extra)
        extra.update(dict(raw_filters.get("extra", {})))
        for key, value in raw_filters.items():
            if key in {"category", "subcategory", "difficulty", "source_type", "chunk_type", "version", "tags", "extra"}:
                continue
            if value in (None, ""):
                continue
            extra[key] = value
        return RetrievalFilters(
            category=coerce(raw_filters.get("category", base_filters.category)),
            subcategory=coerce(raw_filters.get("subcategory", base_filters.subcategory)),
            difficulty=coerce(raw_filters.get("difficulty", base_filters.difficulty)),
            source_type=coerce(raw_filters.get("source_type", base_filters.source_type)),
            chunk_type=coerce(raw_filters.get("chunk_type", base_filters.chunk_type)),
            version=coerce(raw_filters.get("version", base_filters.version)),
            tags=coerce(raw_filters.get("tags", base_filters.tags)),
            extra=extra,
        )

    def _build_semantic_query(self, context: QueryRewriteContext) -> str:
        query = (context.raw_query or "").strip()
        topic = context.resolved_topic or context.session_topic or ""
        if not query:
            return topic

        vague_prefixes = (
            "这个",
            "这个怎么",
            "上一个",
            "那个",
            "它",
            "它和",
        )
        if topic and any(query.startswith(prefix) for prefix in vague_prefixes):
            return (topic + " " + query).strip()

        if topic and topic.lower() not in query.lower():
            return (topic + " " + query).strip()
        return query

    def _build_keyword_query(self, context: QueryRewriteContext, semantic_query: str) -> str:
        tokens = []
        if context.resolved_topic:
            tokens.extend(_TOKEN_PATTERN.findall(context.resolved_topic))
        tokens.extend(_TOKEN_PATTERN.findall(semantic_query))
        seen = set()
        ordered = []
        for token in tokens:
            normalized = token.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(token)
        return " ".join(ordered[:10])

    def _preferred_chunk_types(self, context: QueryRewriteContext) -> Tuple[str, ...]:
        intent = (context.intent or "").strip().lower()
        return INTENT_CHUNK_MAP.get(intent, INTENT_CHUNK_MAP["explain"])

    def _build_filters(self, context: QueryRewriteContext, preferred_chunk_types: Tuple[str, ...]) -> RetrievalFilters:
        base = context.filters
        semantic_query = self._build_semantic_query(context).lower()

        category = list(base.category)
        if not category:
            inferred_category = self._infer_mapping_value(semantic_query, _CATEGORY_HINTS)
            if inferred_category:
                category.append(inferred_category)

        source_type = list(base.source_type)
        if not source_type:
            inferred_source = self._infer_mapping_value(semantic_query, _SOURCE_HINTS)
            if inferred_source:
                source_type.append(inferred_source)

        chunk_type = list(base.chunk_type)
        if not chunk_type:
            chunk_type.extend(preferred_chunk_types)

        difficulty = list(base.difficulty)
        if not difficulty:
            if any(keyword in semantic_query for keyword in ("深入", "高级", "原理")):
                difficulty.append("advanced")
            elif any(keyword in semantic_query for keyword in ("速通", "入门", "简单")):
                difficulty.append("beginner")

        return RetrievalFilters(
            category=coerce_tuple(category),
            subcategory=base.subcategory,
            difficulty=coerce_tuple(difficulty),
            source_type=coerce_tuple(source_type),
            chunk_type=coerce_tuple(chunk_type),
            version=base.version,
            tags=base.tags,
            extra=dict(base.extra),
        )

    @staticmethod
    def _normalize_queries(*queries: Any) -> Tuple[str, ...]:
        normalized = []
        seen = set()
        for query in queries:
            if not query:
                continue
            for item in query if isinstance(query, (list, tuple, set)) else (query,):
                text = str(item).strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(text)
        return tuple(normalized)

    @staticmethod
    def _infer_mapping_value(text: str, mapping: Mapping[str, Tuple[str, ...]]) -> Optional[str]:
        for value, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                return value
        return None

    @staticmethod
    def _looks_ambiguous(query: str) -> bool:
        if not query:
            return False
        if len(query) <= 8:
            return True
        if any(token in query for token in ("怎么", "如何", "区别", "比较", "还是")):
            return True
        return False


def _contains_reference_token(message: str, lowered: str) -> bool:
    return any(token in lowered for token in ("this", "that", "previous", "it")) or any(
        token in message for token in ("这个", "那个", "上一个", "它")
    )


__all__ = [
    "QueryRewriteConfig",
    "QueryRewriteContext",
    "QueryRewriteService",
]
