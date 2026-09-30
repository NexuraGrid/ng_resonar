# Operating resonar

## Deployment layout

```
internet ──► Cloudflare ──► cloudflared (host network, shared with other apps)
                                 │  ngyou.nexuragrid.com → http://localhost:8899
                                 ▼
               127.0.0.1:8899 ──► frontend (nginx-unprivileged :8080)
                                    │  network "edge"
                                    ▼  /api/*
                                 backend (FastAPI, uid 1000) ──► internet
                                    │  network "data" (internal, no route out)   (YouTube, lrclib,
                            ┌───────┴────────┐                                     SponsorBlock,
                           db (Postgres)   redis (sessions, cache, throttle)      Last.fm, LB)
```

| Service  | Published port        | Networks     | Reaches the internet |
|----------|-----------------------|--------------|----------------------|
| frontend | `127.0.0.1:${PORT}`   | edge         | no need              |
| backend  | none (8000 internal)  | edge, data   | yes (media, lyrics)  |
| db       | none                  | data         | no                   |
| redis    | none                  | data         | no                   |

- Only the frontend publishes a port, and only on loopback. The LAN and the
  internet can reach resonar only through the tunnel. That also makes
  `CF-Connecting-IP` (used by the login throttle) trustworthy: nobody can
  reach nginx without going through Cloudflare.
- Every container runs with `no-new-privileges`, all Linux capabilities
  dropped (Postgres/Redis get back only the few their entrypoints need), a
  read-only root filesystem, memory/PID limits, and rotated logs (3×10 MB).
- nginx sends CSP, HSTS, `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy` and `Permissions-Policy` on every response
  (`frontend/security-headers.conf`). If you add an inline `<script>` to
  `index.html`, update the `sha256-…` hash in the CSP or it won't run.
- The backend rejects cookie-authenticated `/api` writes whose `Origin` is
  not this host (the sibling `*.nexuragrid.com` apps are "same-site", so
  `SameSite=Lax` alone doesn't stop them).

## Everyday commands

```bash
docker compose up -d --build        # deploy / update (never add -v)
docker compose ps                   # status (all four "healthy")
docker compose logs -f backend
```

Never run `docker compose down -v`: it deletes `db-data` (every user,
playlist, favourite and history entry) and `redis-data` (sessions).

yt-dlp is intentionally unpinned; rebuild the backend
(`docker compose build --pull backend && docker compose up -d`) when
extraction starts failing.

## Backups

`scripts/backup.sh` writes `postgres.dump` (pg_dump custom format) and
`data.tar.gz` to `$BACKUP_DIR/<timestamp>/` (default `~/backups/resonar`) and
deletes backups older than `$KEEP_DAYS` (default 14). `BACKUP_MEDIA=1` also
archives saved videos in `./media`.

```bash
scripts/backup.sh                          # run once now
scripts/install-backup-timer.sh            # daily at ~03:45 (systemd user timer)
sudo loginctl enable-linger "$USER"        # let the timer run while logged out
systemctl --user list-timers resonar-backup.timer
journalctl --user -u resonar-backup.service   # last run's output
```

**Copy backups off this machine** (NAS, external disk, `rclone`/`restic`).
Also keep the Android TWA signing keystore (`android-twa/android.keystore`,
not in git) and its password somewhere safe — without it the Play Store app
can never be updated.

### Restore

```bash
B=~/backups/resonar/<timestamp>

docker compose stop backend frontend
docker compose exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
  < "$B/postgres.dump"
tar -xzf "$B/data.tar.gz" -C data
docker compose up -d
```

## Rotating secrets

- `POSTGRES_PASSWORD`: only applies when the volume is first created. Change
  the role's password first
  (`docker compose exec db psql -U resonar -c "\password resonar"`), then
  update `.env` and `docker compose up -d`.
- `BOOTSTRAP_TOKEN`: only matters before the first user exists.
- Logging everyone out: `docker compose exec redis redis-cli --scan --pattern 'sess:*' | xargs -r docker compose exec -T redis redis-cli del`.

## Cloudflare tunnel (managed outside this repo)

The `cloudflared-tunnel` container is shared with nxgnotes and other apps, so
this compose file doesn't manage it. Keep the ngyou route pointing at
`http://localhost:8899` (= `PORT` in `.env`). Recommendations:

- Pin its image to a version instead of `:latest`.
- Put Cloudflare Access in front of admin-only hostnames (e.g. `sshhouse`).
