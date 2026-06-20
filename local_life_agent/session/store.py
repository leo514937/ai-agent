"""In-memory session persistence for the local life agent."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..domain.state import SessionState


class InMemorySessionStore:
    """Simple in-memory session store for MVP and local testing."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def load(self, session_id: str) -> SessionState:
        """Load a session snapshot, returning an empty state if missing."""
        if not session_id:
            return SessionState()
        state = self._sessions.get(session_id)
        if state is None:
            return SessionState()
        return state.model_copy(deep=True) if hasattr(state, "model_copy") else deepcopy(state)

    def save(self, session_id: str, state: SessionState) -> None:
        """Persist a session snapshot by value."""
        if not session_id or state is None:
            return
        stored = state.model_copy(deep=True) if hasattr(state, "model_copy") else deepcopy(state)
        self._sessions[session_id] = stored

    def clear(self, session_id: str) -> None:
        """Remove a session snapshot if present."""
        if not session_id:
            return
        self._sessions.pop(session_id, None)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-copied snapshot of all stored sessions."""
        return {sid: state.model_copy(deep=True) for sid, state in self._sessions.items()}


_SESSION_STORE = InMemorySessionStore()


def get_session_store() -> InMemorySessionStore:
    """Return the process-wide session store used by the graph runtime."""
    return _SESSION_STORE


def set_session_store(store: InMemorySessionStore) -> None:
    """Replace the process-wide session store. Useful for isolated tests."""
    global _SESSION_STORE
    _SESSION_STORE = store


def reset_session_store() -> None:
    """Reset the process-wide session store to a fresh empty instance."""
    set_session_store(InMemorySessionStore())

