"""Persisted memory trace snapshots for audit and replay."""

from alembic import op
import sqlalchemy as sa

revision = "r0003_memory_traces"
down_revision = "r0002_memory_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_traces",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(length=128), nullable=False),
        sa.Column("retrieved_memory_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("injected_memory_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("skipped_memories", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("candidate_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("promoted_memory_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("rejected_candidates", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("conflict_resolutions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_memory_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qdrant_degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("trace_id", name="uq_memory_traces_trace_id"),
    )
    op.create_index("ix_memory_traces_user_created_at", "memory_traces", ["user_id", "created_at"])
    op.create_index("ix_memory_traces_session_turn", "memory_traces", ["session_id", "turn_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_traces_session_turn", table_name="memory_traces")
    op.drop_index("ix_memory_traces_user_created_at", table_name="memory_traces")
    op.drop_table("memory_traces")
