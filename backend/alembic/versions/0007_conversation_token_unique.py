"""Konuşma oturum jetonuna tekillik kısıtı

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26

conversations.session_token yalnızca index'liydi, UNIQUE değildi. İki sonucu
vardı:

1. YARIŞ DURUMU: chat.py klasik bir get-or-create yapıyordu. Aynı jetonla iki
   eşzamanlı mesaj iki satır yaratabiliyor, sonrasında scalar_one_or_none()
   MultipleResultsFound fırlatıyor ve o oturum KALICI olarak 500 veriyordu.

2. Jeton artık sunucu tarafından üretiliyor (secrets.token_urlsafe); tekillik
   bu üretimin sağladığı garantiyi veritabanı seviyesinde de zorunlu kılıyor.

KISMİ index kullanıyoruz (WHERE deleted_at IS NULL): silinmiş konuşmalar
jetonlarını tutmaya devam edebilsin, yalnızca AKTİF oturumlar arasında
tekillik aransın. Arama sorgusu da zaten bu filtreyi kullanıyor.

Kısıt eklenmeden önce mevcut çakışmalar temizlenir: her jeton için en son
etkin olan konuşma korunur, diğerleri soft-delete edilir.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_ADI = "uq_conversations_session_token_active"


def upgrade() -> None:
    # 1. Aktif konuşmalar arasındaki jeton çakışmalarını temizle.
    #    Her jeton için en son etkin olanı tut, diğerlerini soft-delete et.
    op.execute(
        """
        WITH sıralı AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY session_token
                       ORDER BY last_active_at DESC NULLS LAST, started_at DESC
                   ) AS sıra
            FROM conversations
            WHERE deleted_at IS NULL
        )
        UPDATE conversations c
        SET deleted_at = NOW(),
            messages_json = '[]'
        FROM sıralı s
        WHERE c.id = s.id AND s.sıra > 1
        """
    )

    op.execute(
        f"CREATE UNIQUE INDEX {INDEX_ADI} "
        f"ON conversations (session_token) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_ADI}")
