#!/bin/sh
# Run pending migrations before uvicorn binds. A failed migration exits the
# container non-zero (compose `restart: unless-stopped` retries) so there is no
# window where the API is served against a stale schema.
set -e

# Scratch space for yt-dlp downloads and batch zips. Leftovers from a crash
# (older than a day, so nothing a live process is using) are swept on start.
mkdir -p "${TMPDIR:-/tmp}"
find "${TMPDIR:-/tmp}" -mindepth 1 -maxdepth 1 -name 'resonar-*' -mmin +1440 \
    -exec rm -rf {} + 2>/dev/null || true

alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
