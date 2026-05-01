"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_token", sa.String(64), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("last_active_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime, nullable=True),
        sa.Column("department_hint", sa.String(64), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="tr"),
        sa.Column("messages_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("retention_expires_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "email_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="COLLECTING_INFO", index=True),
        sa.Column("intent_type", sa.String(64), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=True),
        sa.Column("recipient_name", sa.String(255), nullable=True),
        sa.Column("recipient_department", sa.String(128), nullable=True),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("collected_fields_enc", sa.Text, nullable=True),
        sa.Column("admin_notes", sa.Text, nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("send_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
    )

    op.create_table(
        "email_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.String(36), sa.ForeignKey("email_drafts.id", ondelete="RESTRICT"), unique=True, nullable=False),
        sa.Column("recipient_email_hash", sa.String(64), nullable=False),
        sa.Column("recipient_display", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body_anonymized", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime, nullable=False),
        sa.Column("smtp_message_id", sa.String(255), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime, nullable=False),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "knowledge_base_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("sha256_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("chroma_collection", sa.String(128), nullable=False, server_default="unibox_kb"),
        sa.Column("chroma_doc_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING", index=True),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("uploaded_by", sa.String(128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
        sa.Column("indexed_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tags_json", sa.Text, nullable=False, server_default="[]"),
    )

    op.create_table(
        "request_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email_draft_id", sa.String(36), sa.ForeignKey("email_drafts.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("intent_type", sa.String(64), nullable=False, index=True),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("requires_email", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("raw_classifier_output", sa.Text, nullable=True),
        sa.Column("detected_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("request_intents")
    op.drop_table("knowledge_base_documents")
    op.drop_table("email_logs")
    op.drop_table("email_drafts")
    op.drop_table("conversations")
