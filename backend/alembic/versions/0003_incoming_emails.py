"""Incoming emails tablosu — gelen öğrenci e-postaları

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incoming_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        # IMAP dedup
        sa.Column("message_id", sa.String(512), unique=True, nullable=False, index=True),
        sa.Column("imap_uid", sa.Integer(), nullable=True),
        # Gönderen (KVKK)
        sa.Column("sender_email_enc", sa.Text(), nullable=False),
        sa.Column("sender_email_hash", sa.String(64), nullable=False, index=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        # İçerik
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("attachment_names_json", sa.Text(), server_default="[]", nullable=False),
        # Durum
        sa.Column(
            "status",
            sa.String(32),
            server_default="RECEIVED",
            nullable=False,
            index=True,
        ),
        # Intent
        sa.Column("intent_type", sa.String(64), nullable=True),
        sa.Column("intent_confidence", sa.Float(), nullable=True),
        # RAG
        sa.Column("rag_context_preview", sa.Text(), nullable=True),
        sa.Column("rag_source_count", sa.Integer(), server_default="0", nullable=False),
        # AI yanıtı
        sa.Column("reply_subject", sa.String(512), nullable=True),
        sa.Column("reply_body", sa.Text(), nullable=True),
        # Admin
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        # Gönderim
        sa.Column("send_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("reply_sent_at", sa.DateTime(), nullable=True),
        sa.Column("smtp_message_id", sa.String(255), nullable=True),
        # Zaman
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        # KVKK
        sa.Column("retention_expires_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )


    # email_logs: draft_id nullable yap + incoming_email_id FK ekle
    op.alter_column("email_logs", "draft_id", nullable=True)
    op.add_column(
        "email_logs",
        sa.Column(
            "incoming_email_id",
            sa.String(36),
            sa.ForeignKey("incoming_emails.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("email_logs", "incoming_email_id")
    op.alter_column("email_logs", "draft_id", nullable=False)
    op.drop_table("incoming_emails")
