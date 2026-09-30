#!/usr/bin/env bash
# Installs the daily backup as a systemd *user* timer (no root needed).
# For it to run while you're logged out, also run once:
#   sudo loginctl enable-linger "$USER"
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$units"
sed "s#@REPO_DIR@#$repo#g" "$repo/deploy/systemd/resonar-backup.service" > "$units/resonar-backup.service"
cp "$repo/deploy/systemd/resonar-backup.timer" "$units/resonar-backup.timer"
systemctl --user daemon-reload
systemctl --user enable --now resonar-backup.timer
systemctl --user list-timers resonar-backup.timer --no-pager
