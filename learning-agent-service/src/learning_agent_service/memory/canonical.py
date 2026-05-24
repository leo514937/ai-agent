from __future__ import annotations

import re
from typing import Dict, Iterable, Tuple

_CANONICAL_PATTERN = re.compile("[^a-z0-9\u4e00-\u9fff]+")

CANONICAL_TOPIC_ALIASES = {
    "线程池": "java.concurrent.thread-pool",
    "thread pool": "java.concurrent.thread-pool",
    "jvm gc": "java.jvm.gc",
    "垃圾回收": "java.jvm.gc",
    "langgraph": "agent.langgraph.core",
    "react": "agent.react.pattern",
    "rag": "agent.rag.core",
    "redis": "java.cache.redis",
    "aop": "java.spring.aop",
}


class CanonicalTopicResolver:
    def __init__(self, alias_map: Dict[str, str] = None) -> None:
        self._alias_map = {
            self._normalize(key): value
            for key, value in CANONICAL_TOPIC_ALIASES.items()
        }
        if alias_map:
            self._alias_map.update({self._normalize(key): value for key, value in alias_map.items()})
        self._canonical_values = set(self._alias_map.values())
        self._normalized_canonical_map = {
            self._normalize(value): value
            for value in self._canonical_values
        }

    def canonicalize(self, topic: str) -> str:
        raw_value = (topic or "").strip()
        normalized = self._normalize(topic)
        if not normalized:
            return ""
        if raw_value in self._canonical_values:
            return raw_value
        if normalized in self._alias_map:
            return self._alias_map[normalized]
        if normalized in self._normalized_canonical_map:
            return self._normalized_canonical_map[normalized]
        if "spring" in normalized and "aop" in normalized:
            return "java.spring.aop"
        if "并发" in normalized or "threadpool" in normalized or "thread pool" in topic.lower():
            return "java.concurrent.thread-pool"
        if "jvm" in normalized and ("gc" in normalized or "垃圾回收" in normalized):
            return "java.jvm.gc"
        if "langgraph" in normalized:
            return "agent.langgraph.core"
        if "rag" in normalized:
            return "agent.rag.core"
        return normalized.replace(" ", ".")

    def canonicalize_many(self, topics: Iterable[str]) -> Tuple[str, ...]:
        results = []
        seen = set()
        for topic in topics:
            canonical = self.canonicalize(topic)
            if canonical and canonical not in seen:
                seen.add(canonical)
                results.append(canonical)
        return tuple(results)

    @staticmethod
    def _normalize(topic: str) -> str:
        value = (topic or "").strip().lower()
        value = _CANONICAL_PATTERN.sub(" ", value)
        return " ".join(value.split())
