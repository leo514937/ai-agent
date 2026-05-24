from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionSummaryService:
    max_history_segments: int = 4

    def summarize(
        self,
        current: Any,
        *,
        current_topic: Optional[str] = None,
        open_questions: Optional[list[str]] = None,
        confirmed_facts: Optional[list[str]] = None,
        next_steps: Optional[list[str]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        topic = self._canonical_topic(current_topic or getattr(current, "current_topic", None))
        current_summary = getattr(current, "history_summary", None)
        segments = [segment.strip() for segment in (current_summary or "").split(" -> ") if segment.strip()]
        if topic:
            if topic in segments:
                segments = [segment for segment in segments if segment != topic]
            segments.append(topic)

        open_questions = list(open_questions or getattr(current, "open_questions", []) or [])
        confirmed_facts = list(confirmed_facts or getattr(current, "confirmed_facts", []) or [])
        next_steps = list(next_steps or getattr(current, "next_steps", []) or [])
        if confirmed_facts:
            segments.append("确认:" + "，".join(confirmed_facts[:2]))
        if open_questions:
            segments.append("待解:" + "，".join(open_questions[:2]))
        if next_steps:
            segments.append("下一步:" + "，".join(next_steps[:2]))

        update = {
            "current_topic": topic or getattr(current, "current_topic", None),
            "recent_entities": self._merge_unique(
                list(getattr(current, "recent_entities", []) or []),
                [topic] if topic else [],
                limit=5,
            ),
            "history_summary": " -> ".join(segments[-self.max_history_segments :]) if segments else current_summary,
            "open_questions": self._merge_unique(list(getattr(current, "open_questions", []) or []), open_questions, limit=8),
            "confirmed_facts": self._merge_unique(
                list(getattr(current, "confirmed_facts", []) or []),
                confirmed_facts,
                limit=8,
            ),
            "next_steps": self._merge_unique(list(getattr(current, "next_steps", []) or []), next_steps, limit=5),
            "summary_version": int(getattr(current, "summary_version", 0) or 0) + (1 if topic or open_questions or confirmed_facts or next_steps else 0),
            "summary_updated_at": _utcnow() if topic or open_questions or confirmed_facts or next_steps else getattr(current, "summary_updated_at", None),
        }
        if extra:
            update.setdefault("extra", dict(getattr(current, "extra", {}) or {}))
            update["extra"].update(dict(extra))
        return self._apply_update(current, update)

    @staticmethod
    def _canonical_topic(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return str(value).strip() or None

    @staticmethod
    def _merge_unique(existing: list[str], incoming: list[str], *, limit: int) -> list[str]:
        merged: list[str] = []
        for item in existing + incoming:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
        return merged[:limit]

    @staticmethod
    def _apply_update(current: Any, update: dict[str, Any]) -> Any:
        if hasattr(current, "model_copy"):
            return current.model_copy(update=update)
        if hasattr(current, "__dataclass_fields__"):
            from dataclasses import replace

            return replace(current, **update)
        return update
