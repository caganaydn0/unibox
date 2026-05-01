"""PostgreSQL + pgvector migration

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-20

SQLite + ChromaDB -> PostgreSQL + pgvector geçişi:
- pgvector extension etkinleştir
- knowledge_base_documents: file_data (BYTEA) ekle, chroma sütunlarını kaldır
- document_chunks tablosu oluştur (pgvector embedding sütunu ile)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. knowledge_base_documents: yeni sütunlar ekle
    op.add_column(
        "knowledge_base_documents",
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "knowledge_base_documents",
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
    )

    # 3. knowledge_base_documents: eski sütunları kaldır
    op.drop_column("knowledge_base_documents", "file_path")
    op.drop_column("knowledge_base_documents", "chroma_collection")
    op.drop_column("knowledge_base_documents", "chroma_doc_ids_json")

    # 4. document_chunks tablosu
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("knowledge_base_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("tags_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # 5. pgvector HNSW index (cosine similarity)
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_cosine "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_column("knowledge_base_documents", "chunk_count")
    op.drop_column("knowledge_base_documents", "file_data")
    op.add_column(
        "knowledge_base_documents",
        sa.Column("file_path", sa.String(1024), nullable=True),
    )
    op.add_column(
        "knowledge_base_documents",
        sa.Column("chroma_collection", sa.String(128), server_default="unibox_kb"),
    )
    op.add_column(
        "knowledge_base_documents",
        sa.Column("chroma_doc_ids_json", sa.Text(), server_default="[]"),
    )
    op.execute("DROP EXTENSION IF EXISTS vector")
