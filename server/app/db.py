"""SQLite access + schema (idempotent migrate)."""
import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA_VERSION = 13

SCHEMA = """
-- 1.4: categories
CREATE TABLE IF NOT EXISTS movie_genres (tmdb_id INTEGER NOT NULL, genre TEXT NOT NULL, PRIMARY KEY (tmdb_id, genre));
CREATE INDEX IF NOT EXISTS movie_genres_genre ON movie_genres(genre);
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY,         -- TMDB collection id
    name TEXT NOT NULL,
    poster_path TEXT, backdrop_path TEXT,
    poster TEXT,                    -- cached file name in thumbs/
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created_at INTEGER);
CREATE TABLE IF NOT EXISTS item_tags (item_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY (item_id, tag_id));
CREATE INDEX IF NOT EXISTS item_tags_tag ON item_tags(tag_id);
-- 1.4.1: home rows
CREATE TABLE IF NOT EXISTS movie_recs (tmdb_id INTEGER NOT NULL, rec_id INTEGER NOT NULL, rank INTEGER NOT NULL,
    PRIMARY KEY (tmdb_id, rec_id));            -- TMDB "recommendations" for a movie (first page)
CREATE INDEX IF NOT EXISTS movie_recs_rec ON movie_recs(rec_id);
-- 1.4.3: cast & crew (from the same TMDB details request); photos downloaded on first view
CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_path TEXT, photo TEXT, updated_at INTEGER);
CREATE TABLE IF NOT EXISTS movie_cast (tmdb_id INTEGER NOT NULL, person_id INTEGER NOT NULL, character TEXT, ord INTEGER NOT NULL,
    PRIMARY KEY (tmdb_id, person_id));
CREATE INDEX IF NOT EXISTS movie_cast_person ON movie_cast(person_id);
CREATE TABLE IF NOT EXISTS movie_crew (tmdb_id INTEGER NOT NULL, person_id INTEGER NOT NULL, job TEXT NOT NULL,
    PRIMARY KEY (tmdb_id, person_id, job));
CREATE INDEX IF NOT EXISTS movie_crew_person ON movie_crew(person_id);
CREATE TABLE IF NOT EXISTS home_pins (row TEXT NOT NULL, item_id INTEGER NOT NULL, mode INTEGER NOT NULL,
    created_at INTEGER, PRIMARY KEY (row, item_id));   -- admin: mode 1 = always include, -1 = never
CREATE TABLE IF NOT EXISTS rec_cache (user_id INTEGER NOT NULL, library_id INTEGER NOT NULL, sig TEXT NOT NULL,
    computed_at INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (user_id, library_id));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,            -- smb | nfs
    remote TEXT NOT NULL,          -- //host/share  or  host:/export
    username TEXT, domain TEXT,    -- smb only (password lives in the root-only credentials file)
    options TEXT,                  -- e.g. vers=3.0
    mount_point TEXT NOT NULL,
    last_status TEXT, last_error TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,            -- movies | tv | music | other
    path TEXT NOT NULL,
    share_id INTEGER REFERENCES shares(id) ON DELETE SET NULL,
    scan_interval_h INTEGER NOT NULL DEFAULT 6,
    last_scan INTEGER, last_scan_result TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,      -- video | audio
    kind TEXT NOT NULL,            -- movie | episode | track | video
    title TEXT NOT NULL,
    sort_title TEXT,
    year INTEGER,
    show TEXT, season INTEGER, episode INTEGER, episode_title TEXT,
    artist TEXT, album TEXT, album_artist TEXT, track INTEGER, disc INTEGER, genre TEXT,
    duration REAL,
    container TEXT, vcodec TEXT, acodec TEXT, width INTEGER, height INTEGER,
    bitrate INTEGER, pix_fmt TEXT,
    audio_streams TEXT, subtitle_streams TEXT, external_subs TEXT,
    size INTEGER, mtime REAL,
    thumb TEXT, poster TEXT,
    added_at INTEGER NOT NULL,
    probed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_items_lib ON items(library_id);
CREATE INDEX IF NOT EXISTS ix_items_show ON items(library_id, show, season, episode);
CREATE INDEX IF NOT EXISTS ix_items_album ON items(library_id, album_artist, album, disc, track);
CREATE INDEX IF NOT EXISTS ix_items_added ON items(added_at);
CREATE TRIGGER IF NOT EXISTS items_drop_tags AFTER DELETE ON items BEGIN DELETE FROM item_tags WHERE item_id=old.id; END;
CREATE TRIGGER IF NOT EXISTS items_drop_pins AFTER DELETE ON items BEGIN DELETE FROM home_pins WHERE item_id=old.id; END;
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (user_id, name COLLATE NOCASE)
);
CREATE INDEX IF NOT EXISTS playlists_user ON playlists(user_id);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY,
    playlist_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    added_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS playlist_tracks_pl ON playlist_tracks(playlist_id, position);
CREATE INDEX IF NOT EXISTS playlist_tracks_item ON playlist_tracks(item_id);
CREATE TRIGGER IF NOT EXISTS playlists_drop_tracks AFTER DELETE ON playlists BEGIN
    DELETE FROM playlist_tracks WHERE playlist_id=old.id;
END;
CREATE TRIGGER IF NOT EXISTS items_drop_playlist_tracks AFTER DELETE ON items BEGIN
    DELETE FROM playlist_tracks WHERE item_id=old.id;
END;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
-- TMDB metadata cache (v1.1)
CREATE TABLE IF NOT EXISTS metadata (
    kind TEXT NOT NULL,            -- movie | tv
    tmdb_id INTEGER NOT NULL,
    title TEXT, original_title TEXT, year INTEGER,
    overview TEXT, tagline TEXT, genres TEXT,   -- genres: JSON list of names
    rating REAL, vote_count INTEGER, runtime INTEGER,
    poster TEXT, backdrop TEXT,    -- file names in data/thumbs
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (kind, tmdb_id)
);
CREATE TABLE IF NOT EXISTS tmdb_episodes (
    tv_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
    name TEXT, overview TEXT, still TEXT, still_path TEXT, air_date TEXT, runtime INTEGER, rating REAL,
    PRIMARY KEY (tv_id, season, episode)
);
CREATE TABLE IF NOT EXISTS show_matches (
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    show TEXT NOT NULL,
    tmdb_id INTEGER,               -- NULL = no match
    status TEXT NOT NULL,          -- matched | nomatch | manual | unmatched (user said: use file names)
    checked_at INTEGER NOT NULL,
    PRIMARY KEY (library_id, show)
);
CREATE TABLE IF NOT EXISTS keyframes (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    mtime REAL, data TEXT          -- JSON list of segment boundary times (seconds), or "null" = not remuxable
);
CREATE TABLE IF NOT EXISTS progress (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position REAL NOT NULL DEFAULT 0,
    duration REAL,
    watched INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, item_id)
);
-- 1.7.9: extracted WebVTT (library scan + idle queue). status: ready | pending | retry
CREATE TABLE IF NOT EXISTS subtitle_cache (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    mtime REAL,
    status TEXT NOT NULL,
    path TEXT,
    checked_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, key)
);
CREATE INDEX IF NOT EXISTS subtitle_cache_status ON subtitle_cache(status, checked_at);
-- 1.7.9: opening-clip cache (first ~6s at 1080p). status: ready | pending | retry
CREATE TABLE IF NOT EXISTS prefetch_cache (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    start_t REAL NOT NULL DEFAULT 0,
    mtime REAL,
    profile TEXT NOT NULL DEFAULT '1080p',
    dir TEXT,
    size INTEGER,
    last_access INTEGER,
    status TEXT,
    checked_at INTEGER,
    PRIMARY KEY (item_id, kind, start_t)
);
CREATE INDEX IF NOT EXISTS prefetch_cache_lru ON prefetch_cache(last_access);
-- 1.9: per-library access, email invites, user activity, Gmail connections (schema 10)
CREATE TABLE IF NOT EXISTS user_libraries (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL, PRIMARY KEY (user_id, library_id));
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,      -- sha256 of the one-time token; the raw token only lives in the link
    email TEXT NOT NULL COLLATE NOCASE,
    role TEXT NOT NULL,                   -- view | download
    libraries TEXT,                       -- JSON list of library ids, NULL = all
    note TEXT,
    created_by INTEGER, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    sent_at INTEGER, sent_via TEXT, send_error TEXT, send_count INTEGER NOT NULL DEFAULT 0,
    accepted_at INTEGER, accepted_user_id INTEGER, revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS invites_email ON invites(email);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, ts INTEGER NOT NULL,
    user_id INTEGER, actor TEXT, kind TEXT NOT NULL,
    item_id INTEGER, library_id INTEGER, title TEXT,
    ip TEXT, device TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
CREATE INDEX IF NOT EXISTS activity_user ON activity(user_id, ts);
CREATE INDEX IF NOT EXISTS activity_kind ON activity(kind, ts);
CREATE TABLE IF NOT EXISTS gmail_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL, display_name TEXT, scopes TEXT, connected_at INTEGER NOT NULL, last_used INTEGER,
    status TEXT NOT NULL, last_error TEXT
);
CREATE TABLE IF NOT EXISTS gmail_sends (user_id INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS gmail_sends_user ON gmail_sends(user_id, ts);
-- 2.0: offline downloads (schema 11). Devices are kept as tombstones (revoked_at) so a revoked or deleted
-- account's phone still gets a signed "wipe" answer on its next sync.
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    name TEXT, platform TEXT, app_version TEXT,
    pubkey TEXT NOT NULL UNIQUE,          -- base64 DER SubjectPublicKeyInfo (EC P-256 from the Android Keystore)
    fp TEXT NOT NULL,                     -- base64url sha256 of the DER key (the grant "dev" field)
    caps TEXT,                            -- JSON: what the device can decode (h264, hevc, av1, ac3, eac3, dts, maxh)
    created_at INTEGER NOT NULL, last_sync INTEGER, last_ip TEXT,
    revoked_at INTEGER, revoke_reason TEXT
);
CREATE INDEX IF NOT EXISTS devices_user ON devices(user_id);
CREATE TABLE IF NOT EXISTS offline_grants (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, device_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
    profile TEXT NOT NULL,                -- original | 1080p | 720p | 480p (+ ".hevc")
    audio INTEGER NOT NULL DEFAULT 0,
    job_id INTEGER,                       -- offline_jobs row for a transcoded profile
    bytes INTEGER, sha256 TEXT,           -- of the file the device receives
    title TEXT,                           -- kept for the admin list after the item is gone
    issued_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, renewed_at INTEGER,
    state TEXT NOT NULL,                  -- preparing | ready | downloaded | deleted | revoked | failed
    revoked_at INTEGER, revoke_reason TEXT, done_at INTEGER
);
CREATE INDEX IF NOT EXISTS offline_grants_user ON offline_grants(user_id, state);
CREATE INDEX IF NOT EXISTS offline_grants_device ON offline_grants(device_id, state);
CREATE TABLE IF NOT EXISTS offline_jobs (
    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, profile TEXT NOT NULL, audio INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,                 -- queued | running | paused | ready | failed
    progress REAL, path TEXT, bytes INTEGER, sha256 TEXT, encoder TEXT, error TEXT, mtime REAL,
    created_at INTEGER, started_at INTEGER, finished_at INTEGER, last_access INTEGER,
    UNIQUE(item_id, profile, audio)
);
-- 2.0.2: TV sign-in codes (idempotent; schema stayed 11 so 2.1 could be 12)
CREATE TABLE IF NOT EXISTS pair_codes (
    id INTEGER PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    poll_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL,                 -- pending | approved | consumed | expired | denied
    device TEXT, ua TEXT, ip TEXT,
    user_id INTEGER, approved_at INTEGER, approver_ip TEXT
);
CREATE INDEX IF NOT EXISTS pair_codes_status ON pair_codes(status, expires_at);

-- 2.1: library sharing between Movinite servers (schema 12)
CREATE TABLE IF NOT EXISTS peers (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL UNIQUE,
    name TEXT,
    url TEXT,
    pubkey TEXT NOT NULL,
    direction TEXT NOT NULL,          -- outgoing (I share to them) | incoming (they share to me) | both
    status TEXT NOT NULL,             -- active | paused | revoked
    created_at INTEGER,
    last_seen INTEGER,
    last_error TEXT,
    proxy INTEGER NOT NULL DEFAULT 0  -- 1 = relay playback through this server
);
CREATE TABLE IF NOT EXISTS share_codes (
    id INTEGER PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,   -- sha256 of the one-time code; the raw code is never stored
    libraries TEXT NOT NULL,          -- JSON list of library ids
    perms TEXT NOT NULL,              -- stream | download
    limits TEXT,
    label TEXT,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    used_by_peer INTEGER,
    revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS share_codes_exp ON share_codes(expires_at);
CREATE TABLE IF NOT EXISTS peer_grants (
    peer_id INTEGER NOT NULL,
    library_id INTEGER NOT NULL,
    can_stream INTEGER NOT NULL DEFAULT 1,
    can_download INTEGER NOT NULL DEFAULT 0,
    max_quality TEXT DEFAULT '1080p',
    max_streams INTEGER DEFAULT 2,
    max_mbps INTEGER DEFAULT 20,
    allow_transcode INTEGER DEFAULT 1,
    PRIMARY KEY(peer_id, library_id)
);
CREATE TABLE IF NOT EXISTS remote_libraries (
    id INTEGER PRIMARY KEY,
    peer_id INTEGER NOT NULL,
    remote_library_id INTEGER NOT NULL,
    name TEXT,
    kind TEXT,
    local_name TEXT,
    visible_to TEXT,                  -- JSON user ids, NULL = everyone
    last_sync INTEGER,
    item_count INTEGER,
    hidden_at INTEGER,
    UNIQUE(peer_id, remote_library_id)
);
CREATE TABLE IF NOT EXISTS remote_items (
    id INTEGER PRIMARY KEY,
    remote_library_id INTEGER NOT NULL,
    remote_item_id INTEGER NOT NULL,
    kind TEXT,
    title TEXT,
    year INTEGER,
    tmdb_id INTEGER,
    sort_title TEXT,
    duration REAL,
    poster TEXT,
    backdrop TEXT,
    overview TEXT,
    runtime INTEGER,
    certification TEXT,
    rating REAL,
    genres TEXT,
    added_at INTEGER,
    updated_at INTEGER,
    UNIQUE(remote_library_id, remote_item_id)
);
CREATE INDEX IF NOT EXISTS remote_items_lib ON remote_items(remote_library_id, sort_title);
CREATE INDEX IF NOT EXISTS remote_items_title ON remote_items(title);

-- 2.2: seek-bar trickplay sprites (schema 13)
CREATE TABLE IF NOT EXISTS trickplay_cache (
    item_id INTEGER PRIMARY KEY,
    mtime REAL,
    interval_s REAL,
    width INTEGER,
    height INTEGER,
    columns INTEGER,
    rows INTEGER,
    count INTEGER,
    sheets INTEGER,
    dir TEXT,
    size INTEGER,
    status TEXT,
    last_access INTEGER,
    checked_at INTEGER,
    attempts INTEGER
);
CREATE INDEX IF NOT EXISTS trickplay_cache_lru ON trickplay_cache(last_access);
"""

_local = threading.local()


def connect():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get():
    c = getattr(_local, "conn", None)
    if c is None:
        c = connect()
        _local.conn = c
    return c


@contextmanager
def tx():
    c = get()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


# columns added after v1.0: (table, column, type)
ADDED_COLUMNS = [
    ("items", "tmdb_id", "INTEGER"),          # movies: matched TMDB movie id
    ("items", "meta_status", "TEXT"),         # movies: matched | nomatch | manual | unmatched
    ("items", "meta_checked_at", "INTEGER"),
    # 1.3
    ("items", "edition", "TEXT"),             # "Director's Cut", "Extended", ... (from the file name)
    ("items", "file_title", "TEXT"),          # title as parsed from the file name (before edition stripping)
    ("items", "meta_confidence", "REAL"),     # 0..1 for automatic matches
    ("items", "meta_note", "TEXT"),           # why a match needs review / how it was found
    ("items", "meta_candidate", "INTEGER"),   # TMDB id suggested for review (not applied)
    ("metadata", "release_date", "TEXT"),
    ("metadata", "imdb_id", "TEXT"),
    ("metadata", "poster_path", "TEXT"),      # TMDB image paths (for full-size artwork saved to folders)
    ("metadata", "backdrop_path", "TEXT"),
    ("metadata", "extra", "TEXT"),            # JSON: countries, studios, collection, original language
    ("shares", "allow_write", "INTEGER DEFAULT 0"),
    ("libraries", "art_write", "INTEGER DEFAULT 0"),
    ("libraries", "art_fanart", "INTEGER DEFAULT 0"),
    ("libraries", "art_nfo", "INTEGER DEFAULT 0"),
    ("libraries", "art_overwrite", "INTEGER DEFAULT 0"),
    ("libraries", "art_thumbs", "INTEGER DEFAULT 0"),   # 1.5.5: TV episode thumbnails (<file>-thumb.jpg)
    ("libraries", "sort_order", "INTEGER"),             # 1.6: admin-set display order (see liborder.py)
    ("items", "art_poster", "TEXT"),                    # 1.7.3: folder poster (see folderart.py)
    ("items", "art_tmdb", "INTEGER"),                   # 1.7.3: TMDB id named by the folder .nfo
    ("items", "rotation", "INTEGER"),                    # 1.7.9: display rotation degrees (0 if none)
    ("items", "color_transfer", "TEXT"),                 # 1.7.9: smpte2084 / arib-std-b67 / ...
    ("items", "color_primaries", "TEXT"),                # 2.2
    ("items", "color_space", "TEXT"),                    # 2.2
    ("keyframes", "status", "TEXT"),                     # 1.7.9: ok | partial | retry
    ("keyframes", "checked_at", "INTEGER"),
    ("keyframes", "attempts", "INTEGER"),

    # 1.9: roles, email, per-library access, session devices
    ("users", "role", "TEXT"),
    ("users", "email", "TEXT"),
    ("users", "all_libraries", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "disabled_at", "INTEGER"),
    ("users", "invited_by", "INTEGER"),
    ("sessions", "ip", "TEXT"),
    ("sessions", "ua", "TEXT"),
    ("sessions", "last_seen", "INTEGER"),
    ("sessions", "device", "TEXT"),
    # 2.0: per-user download limits (NULL = the server default, 0 = unlimited)
    ("users", "dl_titles", "INTEGER"),
    ("users", "dl_gb", "REAL"),
    ("users", "dl_devices", "INTEGER"),

    # 1.4: categories (collection / franchise, age rating; cat_v = version of the category fields fetched)
    ("metadata", "collection_id", "INTEGER"),
    ("metadata", "collection_name", "TEXT"),
    ("metadata", "certification", "TEXT"),
    ("metadata", "cat_v", "INTEGER"),
]


def migrate():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = connect()
    try:
        c.execute("PRAGMA journal_mode=WAL")
        try:
            old_pre = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.Error:
            old_pre = None
        if old_pre and int(old_pre[0]) < 8:
            _backup_db(c, 8)              # 1.7.6: snapshot before playlists (idempotent)
        if old_pre and int(old_pre[0]) < 9:
            _backup_db(c, 9)              # 1.7.9: snapshot before start-cache tables (idempotent)
        if old_pre and int(old_pre[0]) < 10:
            _backup_db(c, 10)             # 1.9: snapshot before roles / invites / hashed sessions (idempotent)
        if old_pre and int(old_pre[0]) < 11:
            _backup_db(c, 11)             # 2.0: snapshot before devices / offline downloads (idempotent)
        if old_pre and int(old_pre[0]) < 12:
            _backup_db(c, 12)             # 2.1: snapshot before server-to-server sharing (idempotent)
        if old_pre and int(old_pre[0]) < 13:
            _backup_db(c, 13)             # 2.2: snapshot before trickplay / colour tags (idempotent)
        c.executescript(SCHEMA)
        for table, col, typ in ADDED_COLUMNS:
            have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
        old = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if old and int(old[0]) < 3:
            _upgrade_3(c)
        if old and int(old[0]) < 4:
            _upgrade_4(c)
        if old and int(old[0]) < 7:
            from . import titles
            titles.backfill_progress(c)   # 1.7: watch progress shared by every file of a title (inserts only)
        c.execute("CREATE INDEX IF NOT EXISTS metadata_collection ON metadata(collection_id)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_items_tmdb ON items(tmdb_id)")      # 1.7: versions / copies of a film
        from . import liborder
        liborder.assign_missing(c)      # 1.6: first run orders the libraries Movies, TV, Other videos, Music
        # 1.7.9: a null keyframes row used to mean "never remux this file". Treat those as retryable.
        c.execute("UPDATE keyframes SET status='retry', checked_at=0 WHERE (data IS NULL OR data='null') "
                  "AND (status IS NULL OR status='' OR status='failed')")
        c.execute("UPDATE keyframes SET status='ok' WHERE data IS NOT NULL AND data!='null' AND "
                  "(status IS NULL OR status='')")
        _upgrade_10(c)                  # 1.9: idempotent (roles from is_admin, hash old session tokens)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL")
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        c.commit()
    finally:
        c.close()



def _backup_db(c, ver):
    """Copy the open database to data/media-server.db.pre-schemaN before a schema bump.
    Skips if that file already exists so a later migrate() does not overwrite the first backup."""
    dest = config.DATA_DIR / ("media-server.db.pre-schema%d" % ver)
    if dest.exists():
        return dest
    tmp = config.DATA_DIR / ("media-server.db.pre-schema%d.tmp" % ver)
    if tmp.exists():
        tmp.unlink()
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            c.backup(dst)
            dst.close()
            dst = None
            tmp.replace(dest)
            try:
                dest.chmod(0o600)
            except OSError:
                pass
            return dest
        finally:
            if dst is not None:
                dst.close()
            if tmp.exists() and not dest.exists():
                tmp.unlink()
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _upgrade_10(c):
    """1.9: every user gets a role (admin stays admin, everyone else keeps today's rights = viewer, all libraries).
    Session tokens written before 1.9 are stored in the clear; hash them in place so nobody is signed out."""
    import hashlib
    c.execute("UPDATE users SET role='admin' WHERE is_admin=1 AND (role IS NULL OR role='')")
    c.execute("UPDATE users SET role='view' WHERE (role IS NULL OR role='')")
    c.execute("UPDATE users SET all_libraries=1 WHERE all_libraries IS NULL")
    c.execute("UPDATE users SET is_admin=CASE WHEN role='admin' THEN 1 ELSE 0 END")
    for (tok,) in c.execute("SELECT token FROM sessions").fetchall():
        if tok and not (len(tok) == 64 and all(ch in "0123456789abcdef" for ch in tok)):
            th = hashlib.sha256(("ms1:" + tok).encode()).hexdigest()
            c.execute("UPDATE OR IGNORE sessions SET token=? WHERE token=?", (th, tok))


def _upgrade_4(c):
    """1.4: genre index from the genres already cached (no TMDB calls). Collections and age ratings are
    filled in by the background category pass (tmdb.CAT_VERSION)."""
    import json
    for tid, g in c.execute("SELECT tmdb_id, genres FROM metadata WHERE kind='movie' AND genres IS NOT NULL").fetchall():
        try:
            names = [x for x in json.loads(g or "[]") if isinstance(x, str) and x.strip()]
        except ValueError:
            continue
        for n in names:
            c.execute("INSERT OR IGNORE INTO movie_genres(tmdb_id, genre) VALUES(?,?)", (tid, n.strip()))


def _upgrade_3(c):
    """1.3: split edition words off existing movie titles; sort matched movies by their TMDB title."""
    from . import media
    for iid, title in c.execute("SELECT id, title FROM items WHERE kind='movie'").fetchall():
        t, ed = media.split_edition(title or "")
        if ed and t:
            c.execute("UPDATE items SET file_title=?, title=?, edition=?, sort_title=? WHERE id=?", (title, t, ed, media.sort_key(t), iid))
            # titles that only failed because of the edition words get another automatic try
            c.execute("UPDATE items SET meta_status=NULL WHERE id=? AND meta_status='nomatch'", (iid,))
    c.execute("UPDATE items SET sort_title=(SELECT lower(m.title) FROM metadata m WHERE m.kind='movie' "
              "AND m.tmdb_id=items.tmdb_id) WHERE kind='movie' AND tmdb_id IS NOT NULL AND "
              "meta_status IN ('matched','manual') AND EXISTS(SELECT 1 FROM metadata m WHERE m.kind='movie' "
              "AND m.tmdb_id=items.tmdb_id AND m.title IS NOT NULL)")
    for iid, st in c.execute("SELECT id, sort_title FROM items WHERE kind='movie' AND tmdb_id IS NOT NULL").fetchall():
        c.execute("UPDATE items SET sort_title=? WHERE id=?", (media.sort_key(st or ""), iid))


def rows(sql, args=()):
    return [dict(r) for r in get().execute(sql, args).fetchall()]


def row(sql, args=()):
    r = get().execute(sql, args).fetchone()
    return dict(r) if r else None
