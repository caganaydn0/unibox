"""BGE-M3 geçişi — embedding boyutu 768 -> 1024

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24

nomic-embed-text (768 boyut, ağırlıklı İngilizce) yerine bge-m3 (1024 boyut,
çok dilli) kullanılıyor. Vektör boyutu değiştiği için mevcut embedding'ler
taşınamaz — hepsi NULL'lanır ve yeniden üretilir.

DİKKAT: Bu migration'dan sonra bilgi tabanı yeniden indekslenmelidir,
aksi halde RAG hiçbir sonuç döndürmez:

    cd backend && uv run python ../scripts/reindex_documents.py

Chunk metinleri ve dosya içerikleri (file_data) korunur; yalnızca vektörler
yeniden hesaplanır.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HNSW = (
    "CREATE INDEX ix_document_chunks_embedding_cosine "
    "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
)


def upgrade() -> None:
    # HNSW indeksi boyuta bağlı — kolon tipini değiştirmeden önce düşürülmeli
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_cosine")
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024)"
    )
    op.execute(HNSW)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_cosine")
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768)"
    )
    op.execute(HNSW)
