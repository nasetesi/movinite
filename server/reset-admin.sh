#!/usr/bin/env bash
# reset-admin.sh -- set a new random password for "admin" (or the user named as $1) and print it.
# The account is made an administrator and must choose a new password at next sign-in.
#     sudo bash reset-admin.sh            # resets "admin"
#     sudo bash reset-admin.sh alice      # resets / creates "alice"
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
[ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
[ -x .venv/bin/python ] || { echo "Not installed here (no .venv). Run install.sh first." >&2; exit 1; }
U="${1:-admin}"
RUN_AS=(); id media-server >/dev/null 2>&1 && RUN_AS=(runuser -u media-server --)
"${RUN_AS[@]}" .venv/bin/python -m app.cli reset-admin "$U"
echo "(all existing sign-ins of $U were ended)"
