#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL yedekleme — Faz 6 (YOL_HARİTASI.md).
#
# docker-compose(.prod).yml'deki postgres container'ını pg_dump ile yedekler,
# gzip'ler, eski yedekleri siler. cron/systemd timer ile periyodik çalıştırmak
# için tasarlandı — kendi başına bir servis değil, tek seferlik bir betik.
#
# ÖNEMLİ — FERNET_KEY bu betiğe KASITLI OLARAK dahil değil:
#   - FERNET_KEY olmadan bu yedekteki şifreli sütunlar (collected_fields_enc,
#     sender_email_enc vb.) asla çözülemez — yedek tek başına işe yaramaz.
#   - Ama FERNET_KEY'i bu dump'la AYNI yerde saklamak KVKK açısından yanlış:
#     ikisi birlikte ele geçerse şifrelemenin hiçbir anlamı kalmaz.
#   FERNET_KEY'i AYRI, güvenli bir yerde (parola yöneticisi / secrets kasası)
#   saklayın. Kaybı = tüm şifreli verinin kalıcı kaybı; asla bu script'e ya
#   da backup dizinine eklemeyin.
#
# Kullanım:
#   ./scripts/backup_db.sh
#   BACKUP_DIR=/mnt/backups RETENTION_DAYS=14 ./scripts/backup_db.sh
#
# cron örneği (her gün 03:00, sunucudaki kullanıcının crontab'ı):
#   0 3 * * * /path/to/unibox_1.1/scripts/backup_db.sh >> /var/log/unibox-backup.log 2>&1

CONTAINER="${POSTGRES_CONTAINER:-unibox_postgres}"
DB_NAME="${POSTGRES_DB:-unibox}"
DB_USER="${POSTGRES_USER:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/unibox}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
dosya="$BACKUP_DIR/unibox_${timestamp}.sql.gz"
gecici="${dosya}.tmp"

# Önce gecici dosyaya yaz, sonra atomik mv — pg_dump yarıda kesilirse
# BACKUP_DIR'de yarım/bozuk bir .sql.gz kalmasın (bir sonraki geri yükleme
# denemesinde sessizce başarısız olurdu).
if ! docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$gecici"; then
    echo "HATA: pg_dump başarısız (container=$CONTAINER, db=$DB_NAME)" >&2
    rm -f "$gecici"
    exit 1
fi

mv "$gecici" "$dosya"
echo "Yedek alındı: $dosya ($(du -h "$dosya" | cut -f1))"

# Eski yedekleri temizle.
find "$BACKUP_DIR" -name "unibox_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
