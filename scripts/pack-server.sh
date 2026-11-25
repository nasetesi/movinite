#!/usr/bin/env bash
# pack-server.sh -- build media-server-ver<version>.tar.gz (+ .sha256) from ./server
#   bash scripts/pack-server.sh [output-dir]      (default: ./dist)
# The tarball's top folder is "media-server/", which is what install.sh and update.sh expect.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
V="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' server/app/version.py)"
[ -n "$V" ] || { echo "version not found in server/app/version.py"; exit 1; }
OUTDIR="${1:-$ROOT/dist}"; mkdir -p "$OUTDIR"; OUTDIR="$(cd "$OUTDIR" && pwd)"
OUT="$OUTDIR/media-server-ver$V.tar.gz"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/media-server"
tar -C server --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' --exclude='backups' \
    --exclude='.env' --exclude='ADMIN_PASSWORD' --exclude='tests/testmedia' -cf - . | tar -C "$TMP/media-server" -xf -
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || date +%s)}" \
    -C "$TMP" -czf "$OUT" media-server
( cd "$OUTDIR" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "$OUT"; cat "$OUT.sha256"
