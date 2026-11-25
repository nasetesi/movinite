#!/usr/bin/env bash
# status.sh -- quick health report: service, version, port, shares, disk.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1
VER="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' app/version.py)"
PORT="$(systemctl cat media-server.service 2>/dev/null | sed -n 's/.*--port \([0-9]*\).*/\1/p' | head -1)"; PORT="${PORT:-8099}"
echo "Movinite (media-server) v$VER in $PROJECT_DIR"
S="$(systemctl is-active media-server 2>/dev/null)"; E="$(systemctl is-enabled media-server 2>/dev/null)"
echo "service:  ${S:-unknown}   (enabled: ${E:-no})"
echo "health:   $(curl -fsS -m 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || echo 'NOT answering')"
echo "url:      http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT"
echo "data:     $PROJECT_DIR/data  ($(du -sh data 2>/dev/null | cut -f1) used, thumbnails $(du -sh data/thumbs 2>/dev/null | cut -f1))"
echo "shares:"
found=0
for u in /etc/systemd/system/srv-media\\x2dserver-shares-*.mount; do
  [ -e "$u" ] || continue; found=1
  n="$(basename "$u")"
  printf "   %-45s %s  %s\n" "$(sed -n 's/^What=//p' "$u")" "$(systemctl is-active "$n" 2>/dev/null)" "$(sed -n 's/^Where=//p' "$u")"
done
[ $found = 1 ] || echo "   (none added from the UI)"
echo "ffmpeg:   $(ffmpeg -version 2>/dev/null | head -1 || echo MISSING)"
echo "logs:     journalctl -u media-server -e"
