#!/usr/bin/env bash
# Backs up the resonar stack into $BACKUP_DIR/<timestamp>/, keeping $KEEP_DAYS
# days:
#   postgres.dump   users, playlists, favourites, history, settings
#   data.tar.gz     ./data (legacy JSON, app settings; batch zips excluded)
#   media.tar.gz    ./media saved videos — only with BACKUP_MEDIA=1 (they can
#                   be re-downloaded and get large)
#
#   scripts/backup.sh
#   BACKUP_DIR=/mnt/nas/resonar BACKUP_MEDIA=1 scripts/backup.sh
#
# Copy $BACKUP_DIR off this machine (NAS, external disk, restic/rclone
# remote): a backup on the same disk doesn't survive that disk failing.
# Restore steps: see docs/OPERATIONS.md.
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/resonar}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE=(docker compose -p "${COMPOSE_PROJECT:-resonar}")
[[ -n "${ENV_FILE:-}" ]] && COMPOSE+=(--env-file "$ENV_FILE")

umask 077
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/$stamp"
mkdir -p "$dest"
trap 'echo "backup failed; removing partial $dest" >&2; rm -rf "$dest"' ERR

echo "==> postgres -> $dest/postgres.dump"
"${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$dest/postgres.dump"

echo "==> ./data -> $dest/data.tar.gz"
tar -czf "$dest/data.tar.gz" --exclude='./batches' --exclude='./tmp' -C data .

if [[ "${BACKUP_MEDIA:-0}" == "1" ]]; then
  echo "==> ./media -> $dest/media.tar.gz"
  tar -czf "$dest/media.tar.gz" -C media .
fi
trap - ERR

echo "==> pruning backups older than $KEEP_DAYS days"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +

du -sh "$dest"
echo "backup ok: $dest"
