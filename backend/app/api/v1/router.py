from fastapi import APIRouter

from app.api.v1 import auth, chat, dashboard, email_drafts, incoming_emails, knowledge, logs, monitor

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(email_drafts.router, prefix="/emails", tags=["emails"])
router.include_router(incoming_emails.router, prefix="/incoming", tags=["incoming"])
router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(monitor.router, prefix="/monitor", tags=["monitor"])
router.include_router(logs.router, prefix="/logs", tags=["logs"])
