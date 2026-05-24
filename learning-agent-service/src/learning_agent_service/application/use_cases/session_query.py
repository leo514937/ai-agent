from __future__ import annotations


class SessionQueryService:
    def __init__(self, *, memory_service) -> None:
        self._memory_service = memory_service

    def get(self, session_id: str):
        return self._memory_service.load_any(session_id)
