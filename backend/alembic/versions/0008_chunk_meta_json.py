"""Chunk meta verisi (madde no, başlık, bölüm) + chunk_index tekilliği

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26

Madde-farkındalıklı bölme, chunk başına yapısal bilgi üretiyor: hangi madde,
hangi başlık, hangi bölüm, uzun bir maddenin kaçıncı parçası.

NEDEN tags_json'a yazılmıyor: orası "intent etiketleri" anlamında ve
rag_engine intent bonusunu `intent_type in etiketler` ile hesaplıyor;
evaller de tag üyeliğiyle ölçüyor. Aşırı yükleme ikisini de bozardı.

NEDEN JSONB (TEXT değil): tags_json'un TEXT olması SQLite'tan kalma bir
miras; burada PostgreSQL sabit. JSONB ile ileride meta_json->>'madde_no'
üzerinde filtre/indeks bedava gelir.

DİKKAT: Bu migration'dan sonra TAM YENİDEN İNDEKSLEME gerekir. Mevcut
chunk'lar sabit uzunlukta bölünmüş hâlde kalır ve meta_json'ları boş olur;
karışık granülerlik geri getirimi bozar (bkz. reindex_documents.py):

    cd backend && uv run python ../scripts/reindex_documents.py
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UQ_ADI = "uq_document_chunks_doc_index"


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Mükerrer chunk_index'i engelleyen hiçbir şey yoktu. Komşu birleştirme
    # ve belge sırasına dizme, chunk_index'in doküman içinde tekil ve sıralı
    # olmasına dayanacak.
    op.execute(
        f"""
        WITH yinelenen AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY document_id, chunk_index ORDER BY id
                   ) AS sıra
            FROM document_chunks
        )
        DELETE FROM document_chunks
        WHERE id IN (SELECT id FROM yinelenen WHERE sıra > 1)
        """
    )
    op.create_unique_constraint(
        UQ_ADI, "document_chunks", ["document_id", "chunk_index"]
    )


def downgrade() -> None:
    op.drop_constraint(UQ_ADI, "document_chunks", type_="unique")
    op.drop_column("document_chunks", "meta_json")
