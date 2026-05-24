from __future__ import annotations

import unittest
from datetime import datetime, timezone

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.repositories.preferences import UserProfileProjectionRepository
from learning_agent_service.infrastructure.repositories.records import UserProfilePreferenceRecord


class UserProfileProjectionRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = UserProfileProjectionRepository(self.session_factory)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_upsert_replaces_current_value_and_preserves_active_row(self) -> None:
        first = self.repository.upsert(
            UserProfilePreferenceRecord(
                user_id="user-1",
                preference_key="food.spicy_preference",
                current_value="likes_spicy",
                confidence=0.7,
                source_memory_id="mem-1",
                effective_from=datetime.now(timezone.utc),
            )
        )
        second = self.repository.upsert(
            UserProfilePreferenceRecord(
                user_id="user-1",
                preference_key="food.spicy_preference",
                current_value="no_spicy",
                confidence=0.95,
                source_memory_id="mem-2",
                effective_from=datetime.now(timezone.utc),
            )
        )

        self.assertEqual(first.preference_key, "food.spicy_preference")
        self.assertEqual(second.current_value, "no_spicy")
        active_rows = self.repository.list_active("user-1")
        self.assertEqual(len(active_rows), 1)
        self.assertEqual(active_rows[0].current_value, "no_spicy")
        self.assertTrue(active_rows[0].is_active)


if __name__ == "__main__":
    unittest.main()
