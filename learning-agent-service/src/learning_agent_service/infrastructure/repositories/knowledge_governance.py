"""SQLAlchemy repository for knowledge document governance metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from learning_agent_service.infrastructure.db.models import KnowledgeDocumentModel, KnowledgeDocumentVersionModel

from .base import SqlAlchemyRepositoryBase
from .records import KnowledgeDocumentRecord, KnowledgeDocumentVersionRecord

try:
    from sqlalchemy import select
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select = None


class KnowledgeGovernanceRepository(SqlAlchemyRepositoryBase):
    """Manage document metadata, version activation, invalidation, and rollback."""

    def register_document(self, record: KnowledgeDocumentRecord) -> KnowledgeDocumentModel:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.execute(
                select(KnowledgeDocumentModel).where(KnowledgeDocumentModel.document_id == record.document_id)
            ).scalar_one_or_none()
            if instance is None:
                instance = KnowledgeDocumentModel(document_id=record.document_id)
            instance.title = record.title
            instance.source_uri = record.source_uri
            instance.source_type = record.source_type
            instance.category = record.category
            instance.checksum = record.checksum
            instance.active_version = record.active_version
            instance.status = record.status
            instance.extra = dict(record.extra)
            session.add(instance)
            session.flush()
            return instance

    def register_version(self, record: KnowledgeDocumentVersionRecord) -> KnowledgeDocumentVersionModel:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.execute(
                select(KnowledgeDocumentVersionModel).where(
                    KnowledgeDocumentVersionModel.document_id == record.document_id,
                    KnowledgeDocumentVersionModel.version == record.version,
                )
            ).scalar_one_or_none()
            if instance is None:
                instance = KnowledgeDocumentVersionModel(document_id=record.document_id, version=record.version)
            instance.checksum = record.checksum
            instance.chunk_count = record.chunk_count
            instance.status = record.status
            instance.imported_at = record.imported_at or datetime.now(timezone.utc)
            instance.activated_at = record.activated_at
            instance.invalidated_at = record.invalidated_at
            instance.rollback_from_version = record.rollback_from_version
            instance.extra = dict(record.extra)
            session.add(instance)
            session.flush()
            return instance

    def activate_version(self, document_id: str, version: str) -> Optional[KnowledgeDocumentVersionModel]:
        self._require_sqlalchemy()
        now = datetime.now(timezone.utc)
        with self.session_scope() as session:
            document = session.execute(
                select(KnowledgeDocumentModel).where(KnowledgeDocumentModel.document_id == document_id)
            ).scalar_one_or_none()
            version_row = session.execute(
                select(KnowledgeDocumentVersionModel).where(
                    KnowledgeDocumentVersionModel.document_id == document_id,
                    KnowledgeDocumentVersionModel.version == version,
                )
            ).scalar_one_or_none()
            if document is None or version_row is None:
                return None
            document.active_version = version
            document.status = "active"
            version_row.status = "active"
            version_row.activated_at = now
            session.add(document)
            session.add(version_row)
            session.flush()
            return version_row

    def mark_version_inactive(self, document_id: str, version: str, status: str = "inactive") -> Optional[KnowledgeDocumentVersionModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            version_row = session.execute(
                select(KnowledgeDocumentVersionModel).where(
                    KnowledgeDocumentVersionModel.document_id == document_id,
                    KnowledgeDocumentVersionModel.version == version,
                )
            ).scalar_one_or_none()
            if version_row is None:
                return None
            version_row.status = status
            version_row.invalidated_at = datetime.now(timezone.utc)
            session.add(version_row)
            session.flush()
            return version_row

    def rollback_to_version(self, document_id: str, version: str, rollback_from_version: str) -> Optional[KnowledgeDocumentVersionModel]:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            document = session.execute(
                select(KnowledgeDocumentModel).where(KnowledgeDocumentModel.document_id == document_id)
            ).scalar_one_or_none()
            version_row = session.execute(
                select(KnowledgeDocumentVersionModel).where(
                    KnowledgeDocumentVersionModel.document_id == document_id,
                    KnowledgeDocumentVersionModel.version == version,
                )
            ).scalar_one_or_none()
            if document is None or version_row is None:
                return None
            document.active_version = version
            version_row.status = "active"
            version_row.rollback_from_version = rollback_from_version
            version_row.activated_at = datetime.now(timezone.utc)
            session.add(document)
            session.add(version_row)
            session.flush()
            return version_row
