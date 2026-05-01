#!/usr/bin/env python3
"""Geliştirme ortamı için örnek veri yükleyici.

Kullanım:
    cd backend
    python ../scripts/seed_db.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def main():
    from datetime import datetime, timedelta, timezone
    from app.db.session import AsyncSessionLocal, engine
    from app.db.base import Base
    from app.db.models.conversation import Conversation
    from app.db.models.email_draft import EmailDraft, EmailDraftStatus
    from app.db.models.knowledge_document import KnowledgeDocument, ProcessingStatus

    # Tabloları oluştur
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        # Örnek konuşma
        conv = Conversation(
            session_token="test-session-seed-001",
            started_at=now,
            last_active_at=now,
            retention_expires_at=now + timedelta(days=90),
            department_hint="ogrenci_isleri",
            messages_json='[{"role":"user","content":"Transkript almak istiyorum","ts":"' + now.isoformat() + '"}]',
        )
        session.add(conv)
        await session.flush()

        # Örnek e-posta taslağı (Onay bekliyor)
        draft = EmailDraft(
            conversation_id=conv.id,
            status=EmailDraftStatus.PENDING_APPROVAL,
            intent_type="transcript_request",
            recipient_email="ogrenci-isleri@university.edu.tr",
            recipient_name="Öğrenci İşleri",
            recipient_department="ogrenci_isleri",
            subject="Transkript Belgesi Talebi",
            body="Sayın İlgili Makam,\n\n2024-2025 Bahar dönemi transkriptimin tarafıma gönderilmesini talep ediyorum.\n\nSaygılarımla",
        )
        session.add(draft)

        # Örnek KB dokümanı (PDF BYTEA olarak saklanır)
        doc = KnowledgeDocument(
            filename="kayit-yonetmeligi.pdf",
            original_filename="Kayıt Yönetmeliği 2024.pdf",
            file_data=b"%PDF-1.4 seed placeholder",  # Yer tutucu
            file_size_bytes=26,
            mime_type="application/pdf",
            sha256_hash="a" * 64,
            status=ProcessingStatus.PENDING,
            uploaded_by="admin",
            description="2024 yılı kayıt ve sınav yönetmeliği",
            tags_json='["admissions", "regulations"]',
        )
        session.add(doc)

        await session.commit()

    print("✓ Seed verisi yüklendi.")
    print(f"  Konuşma ID: {conv.id}")
    print(f"  Draft ID: {draft.id}")
    print(f"  Doküman ID: {doc.id}")
    print()
    print("  Dashboard: http://localhost:3000")
    print("  Bekleyen email: http://localhost:3000/emails")


if __name__ == "__main__":
    asyncio.run(main())
