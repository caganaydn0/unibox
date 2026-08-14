"""Pilot/Co-Pilot çalışma modu — system_settings tablosu ve auto_approved kolonu

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "system_mode",
            sa.String(16),
            server_default="CO_PILOT",
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        "INSERT INTO system_settings (id, system_mode) VALUES (1, 'CO_PILOT')"
    )

    op.add_column(
        "incoming_emails",
        sa.Column("auto_approved", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("incoming_emails", "auto_approved")
    op.drop_table("system_settings")
