"""Runtime configuration: read from <root>/.env and the environment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file():
    f = ROOT / ".env"
    if not f.is_file():
        return
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_env_file()


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.environ.get("MS_DATA_DIR") or (ROOT / "data"))
DB_PATH = DATA_DIR / "media-server.db"
THUMB_DIR = DATA_DIR / "thumbs"
TRANSCODE_DIR = DATA_DIR / "transcode"
PREFETCH_DIR = DATA_DIR / "prefetch"   # 1.7.9: opening-clip cache (first ~6s at 1080p)
TRICKPLAY_DIR = DATA_DIR / "trickplay" # 2.2: seek-bar sprite sheets
SUBS_DIR = DATA_DIR / "subs"           # 1.7.9: extracted WebVTT cache
SHARES_DIR = Path(os.environ.get("MS_SHARES_DIR") or "/srv/media-server/shares")
PORT = _int("MS_PORT", 8099)
MAX_TRANSCODES = _int("MS_MAX_TRANSCODES", 4)  # 1.7.7: same login may use several devices; this is the server-wide cap
X264_PRESET = os.environ.get("MS_X264_PRESET") or "veryfast"
HWACCEL = os.environ.get("MS_HWACCEL") or ""
SESSION_DAYS = _int("MS_SESSION_DAYS", 30)
MOUNT_HELPER = os.environ.get("MS_MOUNT_HELPER") or "/usr/local/sbin/media-server-mount"
# TMDB (v1.1). The key can also be set in Settings -> Metadata (stored in the database, wins over .env).
TMDB_KEY = os.environ.get("MS_TMDB_KEY") or ""
TMDB_LANGUAGE = os.environ.get("MS_TMDB_LANGUAGE") or "en-US"
TMDB_API_BASE = (os.environ.get("MS_TMDB_API_BASE") or "https://api.themoviedb.org/3").rstrip("/")
TMDB_IMAGE_BASE = (os.environ.get("MS_TMDB_IMAGE_BASE") or "https://image.tmdb.org/t/p").rstrip("/")
TMDB_MAX_RPS = float(os.environ.get("MS_TMDB_MAX_RPS") or 20)
TMDB_WORKERS = int(os.environ.get("MS_TMDB_WORKERS") or 4)
FFMPEG = os.environ.get("MS_FFMPEG") or "ffmpeg"
FFPROBE = os.environ.get("MS_FFPROBE") or "ffprobe"

for d in (DATA_DIR, THUMB_DIR, TRANSCODE_DIR, PREFETCH_DIR, SUBS_DIR, TRICKPLAY_DIR):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
