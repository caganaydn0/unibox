import logging
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import _sabit_zamanli_esit, decode_access_token
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency: JWT doğrulama — sadece admin dashboard için.

    ÖZNE DOĞRULANIR. Eskiden payload["sub"] hiç kontrol edilmeden
    döndürülüyordu; SECRET_KEY ile imzalanmış `type=access` olan HERHANGİ bir
    jeton tam admin yetkisi veriyordu. Öznenin yapılandırılmış admin adına
    eşit olması artık şart.
    """
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    özne = payload.get("sub")
    if not özne or not _sabit_zamanli_esit(str(özne), settings.ADMIN_USERNAME):
        logger.warning("Tanınmayan özneli jeton reddedildi: sub=%r", özne)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz token öznesi.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return özne
