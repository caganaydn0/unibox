import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# bcrypt'i DOĞRUDAN kullanıyoruz, passlib üzerinden değil.
# passlib 1.7.4 (son sürüm 2020) bcrypt 4.x ile uyumsuz: sürüm tespitinde
# `module 'bcrypt' has no attribute '__about__'` hatası alıyor ve ardından
# her hash çağrısı "password cannot be longer than 72 bytes" ile patlıyordu.
# Yani hash_password/verify_password KURULU SÜRÜMLERLE HİÇ ÇALIŞMIYORDU.

# bcrypt girdiyi 72 baytta kesiyor. UTF-8'de Türkçe karakterler 2 bayt
# tuttuğu için bu sınıra Türkçe parolalarda beklenenden erken ulaşılır.
BCRYPT_MAX_BYTES = 72


def _parola_baytlari(parola: str) -> bytes:
    """Parolayı bcrypt'in kabul ettiği bayt dizisine çevirir.

    Kesme hem hash hem doğrulama yolunda AYNI şekilde yapıldığı için
    tutarlıdır (çok baytlı bir karakterin ortasından kesse bile).
    """
    return parola.encode("utf-8")[:BCRYPT_MAX_BYTES]


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_parola_baytlari(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Bozuk/eksik özet — sistemi açık bırakmaktansa reddet
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_parola_baytlari(plain), bcrypt.gensalt()).decode("ascii")


def _sabit_zamanli_esit(a: str, b: str) -> bool:
    """Sabit zamanlı string karşılaştırması, Türkçe karakter güvenli.

    secrets.compare_digest str girdilerde YALNIZCA ASCII kabul eder ve aksi
    hâlde TypeError fırlatır. Türkçe parola/kullanıcı adı ("yanlış", "şifre")
    girildiğinde giriş ucu temiz bir 401 yerine 500 veriyordu.
    Baytlara çevirerek hem sorunu hem sabit zamanlılığı koruyoruz.
    """
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def kimlik_dogrula(kullanici_adi: str, parola: str) -> bool:
    """Admin kimlik bilgilerini sabit zamanlı olarak doğrular.

    Eskiden auth.py doğrudan `!=` ile karşılaştırıyordu:

        if req.username != settings.ADMIN_USERNAME or req.password != settings.ADMIN_PASSWORD

    İki sorun: (a) `!=` erken çıkışlı, yani karşılaştırma süresi doğru
    karakter sayısıyla değişiyor ve zamanlama sızıntısı oluşturuyor;
    (b) parola düz metin ortam değişkeninde tutuluyordu.

    ADMIN_PASSWORD_HASH tanımlıysa bcrypt kullanılır (üretimde zorunlu),
    aksi hâlde geliştirme kolaylığı için düz metin karşılaştırılır — ama
    yine de sabit zamanlı.

    Not: kullanıcı adı yanlış olsa bile parola doğrulaması ÇALIŞTIRILIR.
    Aksi hâlde yanıt süresi "kullanıcı adı var mı" bilgisini sızdırırdı.
    """
    ad_dogru = _sabit_zamanli_esit(kullanici_adi, settings.ADMIN_USERNAME)

    if settings.ADMIN_PASSWORD_HASH:
        try:
            parola_dogru = verify_password(parola, settings.ADMIN_PASSWORD_HASH)
        except Exception:
            # Bozuk/eksik hash — sistemi açık bırakmaktansa girişi reddet
            logger.error(
                "ADMIN_PASSWORD_HASH geçerli bir bcrypt özeti değil; giriş reddedildi."
            )
            parola_dogru = False
    else:
        if settings.APP_ENV == "production":
            # config doğrulaması bunu zaten engelliyor; buradaki kontrol
            # yapılandırma bir şekilde atlanırsa diye ikinci savunma hattı.
            logger.error("Üretimde ADMIN_PASSWORD_HASH yok; giriş reddedildi.")
            return False
        parola_dogru = _sabit_zamanli_esit(parola, settings.ADMIN_PASSWORD)

    return ad_dogru and parola_dogru


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "refresh"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None
