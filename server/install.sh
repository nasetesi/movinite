#!/usr/bin/env bash
#
# install.sh -- install Movinite, the media server (self-hosted movies / TV / music streaming, Plex/Jellyfin style)
# on an Ubuntu Server (22.04 / 24.04) or Debian VM / LXC.
#
# HOW TO USE (as root, or with sudo):
#
#     mkdir -p /opt && tar -xzf media-server-ver1.0.tar.gz -C /opt
#     cd /opt/media-server
#     sudo bash install.sh
#
#   or simply put install.sh next to the tarball and run  sudo bash install.sh  there -- it extracts the
#   newest media-server-ver*.tar.gz into /opt/media-server and continues from there.
#
# It needs no questions answered. In order, it:
#   1. apt-installs what it needs: python3 + venv, ffmpeg (ffprobe), cifs-utils + smbclient (SMB), nfs-common (NFS),
#      sudo, curl, rsync
#   2. creates a locked-down service user "media-server" (the app never runs as root)
#   3. builds a Python virtualenv (.venv) and installs the pinned requirements
#   4. creates .env from .env.example
#   5. installs the share mount helper (/usr/local/sbin/media-server-mount) + a sudoers rule that lets
#      the service run ONLY that helper as root, so SMB/NFS shares can be added from the web UI
#   6. initialises the database (data/media-server.db) and creates the first admin with a RANDOM
#      password -- printed once at the end AND saved to <install dir>/ADMIN_PASSWORD (root-only, 600)
#   7. 1.5.2: looks for a video card (Intel / AMD / NVIDIA), installs its VA-API / oneVPL drivers, gives the
#      service user the video + render groups, test-encodes on it and turns on hardware transcoding in
#      Settings when the test passes (Settings > Transcoding can change it; a saved choice is never overridden)
#   8. installs + starts the systemd service "media-server", checks it answers, prints the URL
#
# Safe to re-run: .env, the database, thumbnails and an existing admin are NEVER overwritten.
# To upgrade to a newer release use update.sh instead.
#
# Options:
#   --port N      web port (default 8099)
#   --user NAME   service user (default media-server)
#   --skip-apt    do not apt-get anything (packages already present)
#   --no-service  only build the venv / .env / database -- no service user, no systemd unit
#   --help
#
# shellcheck disable=SC2015
set -euo pipefail

APP_NAME="media-server"
APP_PORT="8099"
SVC_USER="media-server"
SKIP_APT="no"
INSTALL_SERVICE="yes"
SHARES_DIR="/srv/media-server/shares"
HELPER_DST="/usr/local/sbin/media-server-mount"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[32mOK\033[0m  %s\n" "$1"; }
warn() { printf "    \033[33m!\033[0m   %s\n" "$1"; }
die()  { printf "\n\033[31mFAILED: %s\033[0m\n" "$1" >&2; exit 1; }

ORIG_ARGS=("$@")
while [ $# -gt 0 ]; do
  case "$1" in
    --port)       APP_PORT="${2:?--port needs a number}"; shift ;;
    --user)       SVC_USER="${2:?--user needs a name}"; shift ;;
    --skip-apt)   SKIP_APT="yes" ;;
    --no-service) INSTALL_SERVICE="no" ;;
    --help|-h)    awk 'NR>1 && /^#/ && !/shellcheck/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "Unknown option: $1  (try --help)" ;;
  esac
  shift
done
case "$APP_PORT" in ''|*[!0-9]*) die "--port must be a number" ;; esac
[[ "$SVC_USER" =~ ^[a-z_][a-z0-9_-]{0,30}$ ]] || die "--user: invalid user name"

cd "$PROJECT_DIR"
# Bootstrap: install.sh run from a folder that holds the release tarball (not the extracted code) ->
# extract the newest media-server-ver*.tar.gz into /opt and run the install.sh inside it.
if [ ! -f main.py ] && ls media-server-ver*.tar.gz >/dev/null 2>&1; then
  # shellcheck disable=SC2012
  TB="$(ls -1 media-server-ver*.tar.gz | sort -V | tail -1)"
  [ "$(id -u)" -eq 0 ] || { command -v sudo >/dev/null || die "run as root"; exec sudo -E bash "$0" "${ORIG_ARGS[@]}"; }
  [ -e /opt/media-server/main.py ] && echo "NOTE: /opt/media-server already exists -- its code is refreshed, .env/data are kept (use update.sh for upgrades)."
  echo "Extracting $TB into /opt ..."
  mkdir -p /opt && tar -xzf "$TB" -C /opt --exclude='media-server/.env' --exclude='media-server/data'
  exec bash /opt/media-server/install.sh "${ORIG_ARGS[@]}"
fi
[ -f requirements.txt ] && [ -f main.py ] && [ -f app/version.py ] || die "Run this from inside the extracted media-server folder (main.py / requirements.txt not found in $PROJECT_DIR)."
VERSION="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' app/version.py)"

# ---------------------------------------------------------------------------
# Root. A fresh LXC is usually root-only and may not even have sudo.
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  if [ "$INSTALL_SERVICE" = "yes" ] || [ "$SKIP_APT" = "no" ]; then
    command -v sudo >/dev/null 2>&1 || die "Not root and sudo is not installed. Run as root:  bash install.sh"
    echo "Re-running with sudo (apt, the service user and systemd need root)..."
    exec sudo -E bash "$0" "${ORIG_ARGS[@]}"
  fi
fi

if [ "$INSTALL_SERVICE" = "yes" ]; then
  case "$PROJECT_DIR" in
    /root/*|/home/*) die "Media Server is in $PROJECT_DIR, which the service user cannot read.
       Move it somewhere like /opt:   mkdir -p /opt && mv '$PROJECT_DIR' /opt/media-server && cd /opt/media-server && bash install.sh" ;;
  esac
fi

echo "Movinite (media-server) v${VERSION} installer -- installing into: $PROJECT_DIR   (web port $APP_PORT)"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
if [ "$SKIP_APT" = "yes" ]; then
  say "Skipping apt (--skip-apt)"
else
  say "Installing system packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  # ffmpeg lives in Ubuntu's "universe" component (on by default on Ubuntu Server, but not on minimal images)
  FF_POL="$(apt-cache policy ffmpeg 2>/dev/null || true)"   # 1.5.2: not "| grep -q" (SIGPIPE under pipefail)
  if ! [[ "$FF_POL" =~ Candidate:\ [0-9] ]]; then
    if [ -f /etc/os-release ] && grep -qi '^ID=ubuntu' /etc/os-release; then
      warn "ffmpeg not available -- enabling the Ubuntu 'universe' repository"
      apt-get install -y software-properties-common >/dev/null 2>&1 || true
      if command -v add-apt-repository >/dev/null; then add-apt-repository -y universe; apt-get update; fi
    fi
  fi
  # ffmpeg: probing, thumbnails and transcoding.  cifs-utils / nfs-common: mounting network shares.
  # smbclient (1.4.14): Add library -> Browse lists SMB shares / folders without mounting them.
  apt-get install -y python3 python3-venv python3-pip ca-certificates curl rsync sudo ffmpeg cifs-utils nfs-common smbclient
  ok "system packages installed"
fi
command -v python3 >/dev/null || die "python3 is missing (re-run without --skip-apt)."
python3 -c 'import venv, ensurepip' 2>/dev/null || die "python3-venv is missing (re-run without --skip-apt)."
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || die "ffmpeg/ffprobe are missing (re-run without --skip-apt)."
command -v mount.cifs >/dev/null || warn "cifs-utils not installed -- SMB shares cannot be mounted from the UI"
command -v mount.nfs  >/dev/null || warn "nfs-common not installed -- NFS shares cannot be mounted from the UI"

# ---------------------------------------------------------------------------
# 2. Service user
# ---------------------------------------------------------------------------
RUN_AS=()
if [ "$INSTALL_SERVICE" = "yes" ]; then
  say "Service user '$SVC_USER'"
  if id "$SVC_USER" >/dev/null 2>&1; then
    ok "user '$SVC_USER' already exists"
  else
    useradd --system --home-dir "$PROJECT_DIR" --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
    ok "created system user '$SVC_USER' (no login shell)"
  fi
  # video/render: access to /dev/dri for optional hardware transcoding
  for g in video render; do getent group "$g" >/dev/null && usermod -aG "$g" "$SVC_USER" || true; done
  RUN_AS=(runuser -u "$SVC_USER" --)
fi

# ---------------------------------------------------------------------------
# 3. Virtualenv + dependencies
# ---------------------------------------------------------------------------
say "Python virtual environment (.venv)"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; else echo "    .venv already exists -- reusing it."; fi
VENV_PY="$PROJECT_DIR/.venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip
say "Installing Python dependencies (requirements.txt)"
"$VENV_PY" -m pip install --quiet -r requirements.txt
"$VENV_PY" -c 'import fastapi, uvicorn' 2>/dev/null || die "fastapi/uvicorn did not install -- pip needs internet access to pypi.org; re-run."
ok "dependencies installed"

# ---------------------------------------------------------------------------
# 4. .env + data folders
# ---------------------------------------------------------------------------
say ".env and data folders"
if [ -f .env ]; then
  ok ".env already exists -- left untouched"
else
  [ -f .env.example ] || die ".env.example is missing from the release."
  cp .env.example .env
  ok ".env created from .env.example"
fi
mkdir -p data/thumbs data/transcode data/prefetch data/subs data/offline backups
chmod 755 "$PROJECT_DIR"
if [ "$INSTALL_SERVICE" = "yes" ]; then
  chown root:"$SVC_USER" .env; chmod 640 .env
  chown -R "$SVC_USER":"$SVC_USER" data
  chmod 750 data
  # code is root-owned and read-only for the service
  chown -R root:root app main.py requirements.txt helpers 2>/dev/null || true
  chmod -R go-w app helpers 2>/dev/null || true
else
  chmod 600 .env
fi

# ---------------------------------------------------------------------------
# 5. Share mount helper + sudoers
# ---------------------------------------------------------------------------
if [ "$INSTALL_SERVICE" = "yes" ]; then
  say "Network share support (SMB / NFS)"
  install -o root -g root -m 0755 helpers/media-server-mount "$HELPER_DST"
  mkdir -p /etc/media-server/credentials
  chmod 755 /etc/media-server; chmod 700 /etc/media-server/credentials
  cat > /etc/media-server/mount.conf <<CONF
# read by $HELPER_DST (written by install.sh)
SHARES_DIR=$SHARES_DIR
SVC_USER=$SVC_USER
CONF
  chmod 644 /etc/media-server/mount.conf
  mkdir -p "$SHARES_DIR"; chmod 755 /srv/media-server "$SHARES_DIR"
  SUDOERS_TMP="$(mktemp)"
  echo "# Media Server: the service may run ONLY the share mount helper as root (written by install.sh)" > "$SUDOERS_TMP"
  echo "$SVC_USER ALL=(root) NOPASSWD: $HELPER_DST" >> "$SUDOERS_TMP"
  if visudo -cf "$SUDOERS_TMP" >/dev/null; then
    install -o root -g root -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/media-server
    ok "mount helper installed: $HELPER_DST (sudoers: /etc/sudoers.d/media-server)"
  else
    warn "sudoers rule failed validation -- shares cannot be added from the UI"
  fi
  rm -f "$SUDOERS_TMP"
  # MS_SHARES_DIR in .env must match the helper
  grep -q '^MS_SHARES_DIR=' .env || echo "MS_SHARES_DIR=$SHARES_DIR" >> .env
fi

# ---------------------------------------------------------------------------
# 6. Database + first admin (random password, generated here)
# ---------------------------------------------------------------------------
say "Database and first admin account"
ADMIN_FILE="$PROJECT_DIR/ADMIN_PASSWORD"
NEW_PW="$("$VENV_PY" -c 'import secrets; print(secrets.token_urlsafe(12))')"
INIT_OUT="$(cd "$PROJECT_DIR" && MS_ADMIN_PASSWORD="$NEW_PW" "${RUN_AS[@]}" "$VENV_PY" -m app.cli init 2>&1)" \
  || { echo "$INIT_OUT"; die "database initialisation failed (output above)."; }
echo "$INIT_OUT" | grep -E '^database:' | sed 's/^/    /'
ADMIN_CREATED="no"
if echo "$INIT_OUT" | grep -q '^ADMIN_STATUS=created'; then
  ADMIN_CREATED="yes"
  ( umask 077
    {
      echo "Movinite first admin account -- created $(date '+%Y-%m-%d %H:%M:%S %Z')"
      echo "username: admin"
      echo "password: $NEW_PW"
      echo ""
      echo "You are asked to choose your own password at first sign-in, after which this"
      echo "file is out of date. Delete it once you have signed in:  rm $ADMIN_FILE"
      echo "Locked out later?  sudo bash $PROJECT_DIR/reset-admin.sh"
    } > "$ADMIN_FILE" )
  chmod 600 "$ADMIN_FILE"; chown root:root "$ADMIN_FILE" 2>/dev/null || true
  ok "created user 'admin' with a random password (saved to $ADMIN_FILE, mode 600)"
else
  ok "an admin already exists -- NOT touched, no password generated"
fi

# ---------------------------------------------------------------------------
# 7. Video card -> hardware transcoding (1.5.2).  Best effort: never fails the install.
# ---------------------------------------------------------------------------
hw_step() {
  say "Video card (hardware transcoding)"
  # shellcheck source=hwsetup.sh
  . "$PROJECT_DIR/hwsetup.sh"
  hw_scan
  hw_packages
  hw_groups
  hw_choose install
}
if [ -f "$PROJECT_DIR/hwsetup.sh" ]; then hw_step || warn "video card setup skipped -- Settings > Transcoding can test it later"; fi

# ---------------------------------------------------------------------------
# 8. systemd service
# ---------------------------------------------------------------------------
HEALTH=""
if [ "$INSTALL_SERVICE" = "yes" ]; then
  say "Installing systemd service '$APP_NAME'"
  cat > "/etc/systemd/system/${APP_NAME}.service" <<UNIT
[Unit]
Description=Media Server - self-hosted movies, TV and music
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
User=${SVC_USER}
Group=${SVC_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${APP_PORT} --no-access-log --timeout-graceful-shutdown 5
Restart=always
RestartSec=3
LimitNOFILE=65535
PrivateTmp=true
Nice=2

[Install]
WantedBy=multi-user.target
UNIT
  if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable "$APP_NAME" >/dev/null 2>&1
    systemctl restart "$APP_NAME"
    for _ in $(seq 1 25); do
      sleep 1
      HEALTH="$(curl -fsS "http://127.0.0.1:${APP_PORT}/api/health" 2>/dev/null)" && break
    done
    if [ -n "$HEALTH" ]; then ok "service is running: $HEALTH"
    else warn "service did not answer within 25 s -- check:  journalctl -u $APP_NAME -e"; fi
  else
    warn "systemd is not running here (container/chroot?) -- unit written but not started."
    echo "    Start it by hand:  runuser -u $SVC_USER -- $PROJECT_DIR/.venv/bin/uvicorn main:app --host 0.0.0.0 --port $APP_PORT"
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; IP="${IP:-<server-ip>}"
LINE="================================================================================"
echo ""
echo "$LINE"
echo "  Movinite v${VERSION} is installed."
echo ""
echo "  Open:      http://${IP}:${APP_PORT}"
if [ "$ADMIN_CREATED" = "yes" ]; then
  echo "  Username:  admin"
  echo "  Password:  $NEW_PW      (also in $ADMIN_FILE)"
  echo "             You will be asked to choose a new password at first sign-in."
else
  echo "  Sign in with your existing account.  Forgot it?  sudo bash reset-admin.sh"
fi
echo ""
echo "  Next: Settings -> Libraries -> Add library (local folder, SMB share or NFS export)."
echo "  Status:   sudo bash $PROJECT_DIR/status.sh"
echo "  Update:   sudo bash $PROJECT_DIR/update.sh /path/to/media-server-verX.Y.tar.gz"
echo "$LINE"
unset NEW_PW
