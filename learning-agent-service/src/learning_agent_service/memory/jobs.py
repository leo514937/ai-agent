from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from learning_agent_service.domain.memory import MemoryTargetStore
from learning_agent_service.domain.utils import utcnow as _utcnow
from learning_agent_service.infrastructure.repositories.memory_record_repository import (
    MemoryRecordRepository,
)

from .orchestrator import MemoryOrchestrator
@dataclass
class MemoryDeletionWorker:
    """幂等删除 worker，负责把删除任务同步到各个存储层。"""

    repository: MemoryRecordRepository
    qdrant_index: Any = None
    redis_runtime: Any = None
    short_term_store: Any = None

    def run_once(self, limit: int = 50) -> dict[str, Any]:
        claimed = self.repository.claim_deletion_jobs(limit=limit)
        succeeded = 0
        failed = 0
        for job in claimed:
            try:
                self._execute(job.target_store, job.memory_id, job.session_id, job.vector_id)
                self.repository.mark_deletion_job_succeeded(job.deletion_job_id)
                succeeded += 1
            except Exception as exc:  # pragma: no cover - worker failure path
                self.repository.mark_deletion_job_failed(job.deletion_job_id, str(exc))
                failed += 1
        return {
            "claimed": len(claimed),
            "succeeded": succeeded,
            "failed": failed,
        }

    def _execute(self, target_store: Any, memory_id: str, session_id: str | None, vector_id: str | None) -> None:
        target_value = target_store.value if hasattr(target_store, "value") else str(target_store)
        if target_value == MemoryTargetStore.POSTGRES.value:
            return
        if target_value == MemoryTargetStore.QDRANT.value:
            self._delete_qdrant(vector_id or memory_id)
            return
        if target_value == MemoryTargetStore.REDIS.value:
            self._delete_redis(session_id)
            return
        raise RuntimeError(f"unsupported deletion target: {target_value}")

    def _delete_qdrant(self, point_id: str) -> None:
        if not point_id:
            return
        if self.qdrant_index is None:
            raise RuntimeError("qdrant_index is not configured")
        delete_many = getattr(self.qdrant_index, "delete_many", None)
        if callable(delete_many):
            delete_many([point_id])
            return
        delete = getattr(self.qdrant_index, "delete", None)
        if callable(delete):
            delete(point_id)
            return
        raise RuntimeError("qdrant_index does not support delete operations")

    def _delete_redis(self, session_id: str | None) -> None:
        if not session_id:
            return
        deleted = False
        if self.redis_runtime is not None:
            client = getattr(self.redis_runtime, "client", None)
            keys = getattr(self.redis_runtime, "keys", None)
            if client is not None and keys is not None:
                redis_keys = [
                    keys.session_state(session_id),
                    keys.summary(session_id),
                    keys.clarification(session_id),
                    keys.tool_cache(session_id),
                ]
                client.delete(*redis_keys)
                deleted = True
        if self.short_term_store is not None:
            if hasattr(self.short_term_store, "windows"):
                self.short_term_store.windows.pop(session_id, None)
                deleted = True
            if hasattr(self.short_term_store, "task_contexts"):
                self.short_term_store.task_contexts.pop(session_id, None)
                deleted = True
        if not deleted:
            raise RuntimeError("redis cleanup target is not configured")


@dataclass
class MemoryOutboxWorker:
    """把 memory outbox 里的待处理事件同步到向量索引。"""

    long_term_store: Any

    def run_once(self, limit: int = 50) -> dict[str, Any]:
        if self.long_term_store is None or not hasattr(self.long_term_store, "process_memory_outbox_once"):
            return {"claimed": 0, "published": 0, "failed": 0, "skipped": 0}
        return dict(self.long_term_store.process_memory_outbox_once(limit=limit))


@dataclass
class MemoryMaintenanceJob:
    """轻量维护入口，供外部调度器周期性调用。"""

    orchestrator: MemoryOrchestrator
    deletion_worker: MemoryDeletionWorker | None = None
    outbox_worker: MemoryOutboxWorker | None = None
    deletion_batch_size: int = 50
    outbox_batch_size: int = 50

    def run(self, user_id: str | None = None) -> dict[str, Any]:
        merged = self.orchestrator.consolidate(user_id=user_id)
        deletion_summary = None
        if self.deletion_worker is not None:
            deletion_summary = self.deletion_worker.run_once(limit=self.deletion_batch_size)
        outbox_summary = None
        if self.outbox_worker is not None:
            outbox_summary = self.outbox_worker.run_once(limit=self.outbox_batch_size)
        return {
            "status": "ok",
            "merged_count": len(merged),
            "store_type": type(self.orchestrator.long_term_store).__name__,
            "deletion_summary": deletion_summary or {"claimed": 0, "succeeded": 0, "failed": 0},
            "outbox_summary": outbox_summary or {"claimed": 0, "published": 0, "failed": 0, "skipped": 0},
        }
