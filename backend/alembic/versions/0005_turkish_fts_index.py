"""Hibrit arama — Türkçe tam metin arama indeksi

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24

Saf vektör araması Türkçe sorularda zayıf kalıyordu (ölçüm: recall@1 %19).
Anahtar kelimesi net olan sorular ("transkript", "kayıt dondurma") için
PostgreSQL'in yerleşik 'turkish' konfigürasyonuyla tam metin araması ekliyoruz.
İki arama RagEngine içinde Reciprocal Rank Fusion ile birleştirilir.

to_tsvector('turkish', content) sabit konfigürasyonla çağrıldığı için IMMUTABLE
sayılır ve fonksiyonel GIN indeksi oluşturulabilir.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_document_chunks_content_fts_tr "
        "ON document_chunks USING gin (to_tsvector('turkish', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_fts_tr")
