from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

import _bootstrap  # noqa: F401

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency in test env
    raise unittest.SkipTest("SQLAlchemy is not installed") from exc

from learning_agent_service.domain.memory import MemoryTrace
from learning_agent_service.infrastructure.db.models import Base
from learning_agent_service.infrastructure.repositories.memory_trace_repository import MemoryTraceRepository


class MemoryTraceRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.repository = MemoryTraceRepository(self.session_factory)

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_create_and_fetch_trace(self) -> None:
        trace = MemoryTrace(
            trace_id="trace-1",
            user_id="user-1",
            session_id="session-1",
            turn_id="turn-1",
            retrieved=["mem-1"],
            injected=["mem-1"],
            skipped=["mem-2"],
            candidate_ids=["cand-1"],
            promoted=["cand-1"],
            rejected=["cand-2"],
            conflict_resolutions=[{"strategy": "supersede_old", "winner_memory_id": "mem-1"}],
            deletion_job_ids=["job-1"],
            total_memory_tokens=128,
            qdrant_degraded=True,
        )

        created = self.repository.create(trace)
        fetched = self.repository.get_by_trace_id("trace-1")

        self.assertIsNotNone(created)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.trace_id, "trace-1")
        self.assertEqual(fetched.user_id, "user-1")
        self.assertEqual(fetched.retrieved, ["mem-1"])
        self.assertEqual(fetched.injected, ["mem-1"])
        self.assertEqual(fetched.skipped, ["mem-2"])
        self.assertEqual(fetched.candidate_ids, ["cand-1"])
        self.assertEqual(fetched.promoted, ["cand-1"])
        self.assertEqual(fetched.rejected, ["cand-2"])
        self.assertEqual(fetched.conflict_resolutions, [{"strategy": "supersede_old", "winner_memory_id": "mem-1"}])
        self.assertEqual(fetched.total_memory_tokens, 128)
        self.assertTrue(fetched.qdrant_degraded)

        self.assertEqual([item.trace_id for item in self.repository.list_by_session("session-1")], ["trace-1"])
        self.assertEqual([item.trace_id for item in self.repository.list_by_turn("turn-1")], ["trace-1"])
        self.assertEqual([item.trace_id for item in self.repository.list_recent_by_user("user-1")], ["trace-1"])

    def test_list_recent_by_user_orders_newest_first(self) -> None:
        older = MemoryTrace(
            trace_id="trace-older",
            user_id="user-2",
            session_id="session-a",
            turn_id="turn-a",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        newer = MemoryTrace(
            trace_id="trace-newer",
            user_id="user-2",
            session_id="session-b",
            turn_id="turn-b",
            created_at=datetime.now(timezone.utc),
        )

        self.repository.create(older)
        self.repository.create(newer)

        traces = self.repository.list_recent_by_user("user-2")
        self.assertEqual([item.trace_id for item in traces], ["trace-newer", "trace-older"])


if __name__ == "__main__":
    unittest.main()
