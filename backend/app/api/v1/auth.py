import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.config import settings
from app.core.ratelimit import LOGIN_LIMIT, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    kimlik_dogrula,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
async def login(req: LoginRequest, request: Request):
    """Admin giriş — kullanıcı adı + şifre → JWT."""
    if not kimlik_dogrula(req.username, req.password):
        # Başarısız denemeleri logla: kaba kuvvet saldırısının tek görünür izi.
        # Parola ASLA loglanmaz.
        logger.warning(
            "Başarısız giriş denemesi: kullanıcı=%r, kaynak=%s",
            req.username[:32], request.client.host if request.client else "?",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hatalı kullanıcı adı veya şifre.",
        )
    logger.info("Admin girişi başarılı: %s", req.username)
    # Jetonun öznesi her zaman yapılandırılmış admin adı — istemcinin
    # gönderdiği değer değil (büyük/küçük harf farkı vb. taşımasın).
    return TokenResponse(
        access_token=create_access_token(settings.ADMIN_USERNAME),
        refresh_token=create_refresh_token(settings.ADMIN_USERNAME),
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    """Refresh token ile yeni access token al."""
    payload = decode_refresh_token(req.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş refresh token.",
        )
    subject = payload["sub"]
    return TokenResponse(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


@router.post("/logout")
async def logout():
    """Logout — JWT stateless olduğu için client-side token silme yeterli."""
    return {"detail": "Başarıyla çıkış yapıldı."}
