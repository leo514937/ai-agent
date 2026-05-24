from __future__ import annotations

from typing import Iterable, List

from learning_agent_service.domain import ReferenceResolutionResult

from .models import ReferenceResolution, ReferenceResolutionRequest

_CN_THIS = "\u8fd9\u4e2a"
_CN_THAT = "\u90a3\u4e2a"
_CN_PREVIOUS = "\u4e0a\u4e00\u4e2a"
_CN_IT = "\u5b83"


class ReferenceResolver:
    def resolve(self, request: ReferenceResolutionRequest) -> ReferenceResolution:
        candidates = self._candidate_entities(request)
        if _contains_reference_token(request.message, request.lowered_message):
            if candidates:
                return ReferenceResolution(
                    resolved=True,
                    confidence=0.76,
                    resolved_entity=candidates[0],
                    candidate_entities=candidates[:3],
                )
            return ReferenceResolution(resolved=False, confidence=0.24, candidate_entities=())

        if request.follow_up_intent and request.current_topic:
            return ReferenceResolution(
                resolved=True,
                confidence=0.61,
                resolved_entity=request.current_topic,
                candidate_entities=candidates[:3],
            )

        return ReferenceResolution(
            resolved=False,
            confidence=0.0,
            candidate_entities=candidates[:3],
        )

    def to_domain(self, resolution: ReferenceResolution) -> ReferenceResolutionResult:
        return ReferenceResolutionResult(
            resolved=resolution.resolved,
            confidence=resolution.confidence,
            resolved_entity=resolution.resolved_entity,
            candidate_entities=list(resolution.candidate_entities),
            extra=dict(resolution.metadata),
        )

    def _candidate_entities(self, request: ReferenceResolutionRequest) -> tuple[str, ...]:
        candidates: List[str] = []
        candidates.extend(request.pending_clarification_values)
        if request.clarification_result:
            selected = request.clarification_result.get("selected_topic") or request.clarification_result.get("value")
            if selected:
                candidates.append(str(selected))
        if request.current_topic:
            candidates.append(request.current_topic)
        if request.last_retrieval_topic:
            candidates.append(request.last_retrieval_topic)
        candidates.extend(request.recent_entities)
        return tuple(_unique(candidates))


def _contains_reference_token(message: str, lowered: str) -> bool:
    return any(token in lowered for token in ("this", "that", "previous", "it")) or any(
        token in message for token in (_CN_THIS, _CN_THAT, _CN_PREVIOUS, _CN_IT)
    )


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
