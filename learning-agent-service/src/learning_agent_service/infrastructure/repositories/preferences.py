"""SQLAlchemy repository for durable user answer-style preferences."""

from __future__ import annotations

from typing import Any

from learning_agent_service.domain.utils import utcnow as _utcnow
from learning_agent_service.infrastructure.db.models import (
    UserPreferenceProfileModel,
    UserProfilePreferenceModel,
)

from .base import SqlAlchemyRepositoryBase
from .records import UserPreferenceProfileRecord, UserProfilePreferenceRecord

try:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
except ImportError:  # pragma: no cover - depends on optional runtime installation.
    select: Any = None
    IntegrityError = Exception


class UserPreferenceRepository(SqlAlchemyRepositoryBase):
    """Read/write access for durable user preference profiles."""

    def get(self, user_id: str) -> UserPreferenceProfileModel | None:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            return session.execute(
                select(UserPreferenceProfileModel).where(UserPreferenceProfileModel.user_id == user_id)
            ).scalar_one_or_none()

    def upsert(self, record: UserPreferenceProfileRecord) -> UserPreferenceProfileModel:
        self._require_sqlalchemy()
        with self.session_scope() as session:
            instance = session.execute(
                select(UserPreferenceProfileModel).where(UserPreferenceProfileModel.user_id == record.user_id)
            ).scalar_one_or_none()
            if instance is None:
                instance = UserPreferenceProfileModel(user_id=record.user_id)
            instance.answer_style = record.answer_style
            instance.explanation_depth = record.explanation_depth
            instance.extra = dict(record.extra)
            session.add(instance)
            session.flush()
            return instance
class UserProfileProjectionRepository(SqlAlchemyRepositoryBase):
    """Current user profile projection keyed by normalized preference name."""

    def list_active(self, user_id: str) -> list[UserProfilePreferenceModel]:
        self._require_sqlalchemy()
        now = _utcnow()
        with self.session_scope() as session:
            return list(
                session.execute(
                    select(UserProfilePreferenceModel).where(
                        UserProfilePreferenceModel.user_id == user_id,
                        UserProfilePreferenceModel.is_active.is_(True),
                        UserProfilePreferenceModel.effective_from <= now,
                        (
                            (UserProfilePreferenceModel.effective_to.is_(None))
                            | (UserProfilePreferenceModel.effective_to > now)
                        ),
                    ).order_by(UserProfilePreferenceModel.updated_at.desc())
                ).scalars()
            )

    def get(self, user_id: str, preference_key: str) -> UserProfilePreferenceModel | None:
        self._require_sqlalchemy()
        now = _utcnow()
        with self.session_scope() as session:
            return session.execute(
                select(UserProfilePreferenceModel).where(
                    UserProfilePreferenceModel.user_id == user_id,
                    UserProfilePreferenceModel.preference_key == preference_key,
                    UserProfilePreferenceModel.is_active.is_(True),
                    UserProfilePreferenceModel.effective_from <= now,
                    (
                        (UserProfilePreferenceModel.effective_to.is_(None))
                        | (UserProfilePreferenceModel.effective_to > now)
                    ),
                ).order_by(UserProfilePreferenceModel.updated_at.desc())
            ).scalar_one_or_none()

    def upsert(self, record: UserProfilePreferenceRecord) -> UserProfilePreferenceModel:
        self._require_sqlalchemy()
        for attempt in range(2):
            try:
                with self.session_scope() as session:
                    active_rows = list(
                        session.execute(
                            select(UserProfilePreferenceModel).where(
                                UserProfilePreferenceModel.user_id == record.user_id,
                                UserProfilePreferenceModel.preference_key == record.preference_key,
                                UserProfilePreferenceModel.is_active.is_(True),
                            )
                        ).scalars()
                    )
                    for row in active_rows:
                        if row.current_value == record.current_value and row.status == record.status:
                            row.confidence = max(float(row.confidence or 0.0), float(record.confidence or 0.0))
                            row.source_memory_id = record.source_memory_id
                            row.source_session_id = record.source_session_id
                            row.effective_from = record.effective_from or row.effective_from
                            row.effective_to = record.effective_to
                            row.status = record.status
                            row.is_active = record.is_active
                            row.extra = dict(record.extra)
                            row.updated_at = _utcnow()
                            session.add(row)
                            session.flush()
                            return row
                        row.is_active = False
                        row.status = "inactive"
                        row.effective_to = record.effective_from or _utcnow()
                        row.updated_at = _utcnow()
                        session.add(row)

                    instance = UserProfilePreferenceModel(
                        user_id=record.user_id,
                        preference_key=record.preference_key,
                        current_value=record.current_value,
                        confidence=float(record.confidence or 0.0),
                        source_memory_id=record.source_memory_id,
                        effective_from=record.effective_from or _utcnow(),
                        effective_to=record.effective_to,
                        status=record.status,
                        is_active=record.is_active,
                        source_session_id=record.source_session_id,
                        extra=dict(record.extra),
                    )
                    session.add(instance)
                    session.flush()
                    return instance
            except IntegrityError:
                if attempt == 0:
                    continue
                raise
