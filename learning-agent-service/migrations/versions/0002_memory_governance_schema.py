"""Governed memory schema for enterprise memory records and traces."""

from alembic import op
import sqlalchemy as sa

revision = "r0002_memory_governance"
down_revision = "r0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("memory_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="system_event"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("stability", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("sensitivity", sa.String(length=32), nullable=False, server_default="public"),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("should_vectorize", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("entities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("evidence_turn_id", sa.String(length=128), nullable=True),
        sa.Column("source_message_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supersedes", sa.String(length=128), nullable=True),
        sa.Column("superseded_by", sa.String(length=128), nullable=True),
        sa.Column("vector_id", sa.String(length=128), nullable=True),
        sa.Column("raw_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_version", sa.String(length=32), nullable=False, server_default="2"),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("memory_id", name="uq_memory_records_memory_id"),
    )
    op.create_index("ix_memory_records_user_type_scope_status", "memory_records", ["user_id", "memory_type", "scope", "status"])
    op.create_index("ix_memory_records_user_topic", "memory_records", ["user_id", "topic"])
    op.create_index("ix_memory_records_user_summary", "memory_records", ["user_id", "summary"])

    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("candidate_id", sa.String(length=128), nullable=False),
        sa.Column("memory_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="model_inferred"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("stability", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("sensitivity", sa.String(length=32), nullable=False, server_default="public"),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("should_vectorize", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_turn_id", sa.String(length=128), nullable=True),
        sa.Column("source_message_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supersedes", sa.String(length=128), nullable=True),
        sa.Column("superseded_by", sa.String(length=128), nullable=True),
        sa.Column("vector_id", sa.String(length=128), nullable=True),
        sa.Column("raw_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("governance_action", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("require_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_id", name="uq_memory_candidates_candidate_id"),
    )
    op.create_index("ix_memory_candidates_user_status", "memory_candidates", ["user_id", "status"])
    op.create_index("ix_memory_candidates_user_topic", "memory_candidates", ["user_id", "topic"])

    op.create_table(
        "memory_edges",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("edge_id", sa.String(length=128), nullable=False),
        sa.Column("source_memory_id", sa.String(length=128), sa.ForeignKey("memory_records.memory_id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_memory_id", sa.String(length=128), sa.ForeignKey("memory_records.memory_id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False, server_default="related_to"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("edge_id", name="uq_memory_edges_edge_id"),
    )
    op.create_index("ix_memory_edges_source_target", "memory_edges", ["source_memory_id", "target_memory_id"])
    op.create_index("ix_memory_edges_type", "memory_edges", ["edge_type"])

    op.create_table(
        "memory_access_logs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("access_log_id", sa.String(length=128), nullable=False),
        sa.Column("memory_id", sa.String(length=128), sa.ForeignKey("memory_records.memory_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("turn_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False, server_default="read"),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("access_log_id", name="uq_memory_access_logs_access_log_id"),
    )
    op.create_index("ix_memory_access_logs_memory_user", "memory_access_logs", ["memory_id", "user_id"])
    op.create_index("ix_memory_access_logs_accessed_at", "memory_access_logs", ["accessed_at"])

    op.create_table(
        "memory_deletion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("deletion_job_id", sa.String(length=128), nullable=False),
        sa.Column("memory_id", sa.String(length=128), sa.ForeignKey("memory_records.memory_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("target_store", sa.String(length=32), nullable=False, server_default="postgres"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("vector_id", sa.String(length=128), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("deletion_job_id", name="uq_memory_deletion_jobs_deletion_job_id"),
    )
    op.create_index("ix_memory_deletion_jobs_status_scheduled", "memory_deletion_jobs", ["status", "scheduled_at"])
    op.create_index("ix_memory_deletion_jobs_memory_id", "memory_deletion_jobs", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_deletion_jobs_memory_id", table_name="memory_deletion_jobs")
    op.drop_index("ix_memory_deletion_jobs_status_scheduled", table_name="memory_deletion_jobs")
    op.drop_table("memory_deletion_jobs")

    op.drop_index("ix_memory_access_logs_accessed_at", table_name="memory_access_logs")
    op.drop_index("ix_memory_access_logs_memory_user", table_name="memory_access_logs")
    op.drop_table("memory_access_logs")

    op.drop_index("ix_memory_edges_type", table_name="memory_edges")
    op.drop_index("ix_memory_edges_source_target", table_name="memory_edges")
    op.drop_table("memory_edges")

    op.drop_index("ix_memory_candidates_user_topic", table_name="memory_candidates")
    op.drop_index("ix_memory_candidates_user_status", table_name="memory_candidates")
    op.drop_table("memory_candidates")

    op.drop_index("ix_memory_records_user_summary", table_name="memory_records")
    op.drop_index("ix_memory_records_user_topic", table_name="memory_records")
    op.drop_index("ix_memory_records_user_type_scope_status", table_name="memory_records")
    op.drop_table("memory_records")
