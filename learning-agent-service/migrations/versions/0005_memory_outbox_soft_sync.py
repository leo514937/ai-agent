"""Memory outbox, active uniqueness, and vector sync retry support."""

from alembic import op
import sqlalchemy as sa

revision = "r0005_memory_outbox_soft_sync"
down_revision = "r0004_memory_conflict_projection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_memory_records_user_normalized_key_active",
        "memory_records",
        ["user_id", "normalized_key"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_user_profile_preference_user_key_active",
        "user_profile_preference",
        ["user_id", "preference_key"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "memory_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("memory_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("turn_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("vector_id", sa.String(length=128), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedupe_key", name="uq_memory_outbox_dedupe_key"),
    )
    op.create_index("ix_memory_outbox_status_available_at", "memory_outbox", ["status", "available_at"])
    op.create_index("ix_memory_outbox_memory_id", "memory_outbox", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_outbox_memory_id", table_name="memory_outbox")
    op.drop_index("ix_memory_outbox_status_available_at", table_name="memory_outbox")
    op.drop_table("memory_outbox")

    op.drop_index("uq_user_profile_preference_user_key_active", table_name="user_profile_preference")
    op.drop_index("uq_memory_records_user_normalized_key_active", table_name="memory_records")

