"""Small key/value settings stored in the database (editable from the UI)."""
from . import config, db

DEFAULTS = {"tmdb_key": "", "tmdb_language": "", "tmdb_enabled": "1", "server_name": ""}


def get(key, default=None):
    r = db.row("SELECT value FROM settings WHERE key=?", (key,))
    if r is not None and r["value"] is not None:
        return r["value"]
    return DEFAULTS.get(key, default) if default is None else default


def put(key, value):
    with db.tx() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))


def tmdb_key():
    """DB setting wins over .env MS_TMDB_KEY."""
    return (get("tmdb_key") or config.TMDB_KEY or "").strip()


def tmdb_language():
    return (get("tmdb_language") or config.TMDB_LANGUAGE or "en-US").strip()


def tmdb_enabled():
    return get("tmdb_enabled", "1") != "0" and bool(tmdb_key())
