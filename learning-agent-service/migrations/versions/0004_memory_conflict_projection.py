"""Memory conflict lifecycle fields and current profile projection."""

from alembic import op
import sqlalchemy as sa

revision = "r0004_memory_conflict_projection"
down_revision = "r0003_memory_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_records", sa.Column("source_session_id", sa.String(length=128), nullable=True))
    op.add_column("memory_records", sa.Column("normalized_key", sa.String(length=128), nullable=True))
    op.add_column("memory_records", sa.Column("normalized_value", sa.String(length=255), nullable=True))
    op.add_column("memory_records", sa.Column("persistence_scope", sa.String(length=32), nullable=False, server_default="long_term"))
    op.add_column("memory_records", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("memory_records", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_records", sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("memory_records", sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_records", sa.Column("superseded_by_memory_id", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_memory_records_user_normalized_key_status",
        "memory_records",
        ["user_id", "normalized_key", "status"],
    )
    op.create_index("ix_memory_records_user_active", "memory_records", ["user_id", "is_active"])

    op.create_table(
        "user_profile_preference",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("preference_key", sa.String(length=128), nullable=False),
        sa.Column("current_value", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("source_memory_id", sa.String(length=128), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_session_id", sa.String(length=128), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_user_profile_preference_user_key_status",
        "user_profile_preference",
        ["user_id", "preference_key", "status"],
    )
    op.create_index(
        "ix_user_profile_preference_user_active",
        "user_profile_preference",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_profile_preference_user_active", table_name="user_profile_preference")
    op.drop_index("ix_user_profile_preference_user_key_status", table_name="user_profile_preference")
    op.drop_table("user_profile_preference")

    op.drop_index("ix_memory_records_user_active", table_name="memory_records")
    op.drop_index("ix_memory_records_user_normalized_key_status", table_name="memory_records")
    op.drop_column("memory_records", "superseded_by_memory_id")
    op.drop_column("memory_records", "effective_to")
    op.drop_column("memory_records", "effective_from")
    op.drop_column("memory_records", "last_seen_at")
    op.drop_column("memory_records", "is_active")
    op.drop_column("memory_records", "persistence_scope")
    op.drop_column("memory_records", "normalized_value")
    op.drop_column("memory_records", "normalized_key")
    op.drop_column("memory_records", "source_session_id")
