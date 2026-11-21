#!/usr/bin/env sh
# Nightly backup: the database (pg_dump) and uploaded files (videos, attachments).
# Run from the repo folder on the server, e.g. from cron:
#   30 1 * * * cd /opt/hevo-training && ./deploy/backup/backup.sh >> backups/backup.log 2>&1
# Keeps the last KEEP_DAYS days (default 14). Copy backups/ off the server too —
# a backup on the same disk doesn't survive losing that disk.
set -eu

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p backups

# Database: custom format, restorable with pg_restore (see DEPLOY.md).
$COMPOSE exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/db-$STAMP.dump"

# Uploaded files: the media volume as a tarball.
$COMPOSE run --rm --no-deps -T -v "$(pwd)/backups:/backups" --entrypoint sh web \
  -c "tar -czf /backups/media-$STAMP.tar.gz -C /var/media ."

find backups -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find backups -name 'media-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u) backup ok: db-$STAMP.dump media-$STAMP.tar.gz"
