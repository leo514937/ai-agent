"""Initial durable infrastructure schema for the learning agent service."""

from alembic import op
import sqlalchemy as sa

revision = "r0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_mastery",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("review_priority", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("source_turn_id", sa.String(length=128), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "topic", name="uq_topic_mastery_user_topic"),
    )
    op.create_index("ix_topic_mastery_user_review_priority", "topic_mastery", ["user_id", "review_priority"])

    op.create_table(
        "user_preference_profile",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("answer_style", sa.String(length=64), nullable=True),
        sa.Column("explanation_depth", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_user_preference_profile_user"),
    )

    op.create_table(
        "clarification_record",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(length=128), nullable=False),
        sa.Column("ambiguity_type", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("selected_option_id", sa.String(length=128), nullable=True),
        sa.Column("selected_option_label", sa.String(length=255), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_clarification_record_session_turn", "clarification_record", ["session_id", "turn_id"])

    op.create_table(
        "tool_invocation_log",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("degraded_to", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tool_call_id", name="uq_tool_invocation_log_tool_call_id"),
    )
    op.create_index("ix_tool_invocation_log_session_turn", "tool_invocation_log", ["session_id", "turn_id"])

    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("active_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", name="uq_knowledge_document_document_id"),
    )
    op.create_index("ix_knowledge_document_source_type_category", "knowledge_document", ["source_type", "category"])

    op.create_table(
        "knowledge_document_version",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(length=128), sa.ForeignKey("knowledge_document.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="inactive"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_from_version", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_document_version_doc_version"),
    )
    op.create_index("ix_knowledge_document_version_document_status", "knowledge_document_version", ["document_id", "status"])

    op.create_table(
        "outbox_event",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_event_dedupe_key"),
    )
    op.create_index("ix_outbox_event_status_available_at", "outbox_event", ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_event_status_available_at", table_name="outbox_event")
    op.drop_table("outbox_event")

    op.drop_index("ix_knowledge_document_version_document_status", table_name="knowledge_document_version")
    op.drop_table("knowledge_document_version")

    op.drop_index("ix_knowledge_document_source_type_category", table_name="knowledge_document")
    op.drop_table("knowledge_document")

    op.drop_index("ix_tool_invocation_log_session_turn", table_name="tool_invocation_log")
    op.drop_table("tool_invocation_log")

    op.drop_index("ix_clarification_record_session_turn", table_name="clarification_record")
    op.drop_table("clarification_record")

    op.drop_table("user_preference_profile")

    op.drop_index("ix_topic_mastery_user_review_priority", table_name="topic_mastery")
    op.drop_table("topic_mastery")
