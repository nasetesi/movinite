"""1.7.3: a folder poster that belongs to a different film.

A poster.jpg (or <file>-poster.jpg ...) next to a movie normally wins over the TMDB poster.  But when the .nfo in
that folder names a different TMDB id than the movie's current match, the folder art is another film's -- typically
artwork saved by an earlier, wrong automatic match ("Adore (2013)" first matched to "Je t'adore", poster.jpg +
movie.nfo written for that film, later matched by hand to Adoration / Adore 111190).  Then the TMDB poster of the
current match is shown instead, everywhere (cards, details page, home rows), without touching the folder.

items.art_poster = thumb-cache name of the folder poster (NULL = the folder has none)
items.art_tmdb   = TMDB id named by the folder .nfo (0 = no .nfo / no TMDB id in it, NULL = not checked yet)
items.poster     = the poster actually shown, recomputed from those by apply()
"""
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import db, media

log = logging.getLogger("media-server.folderart")

OWN_MARKERS = (b"written by Movinite", b"written by Media Server")
_ID_RES = (re.compile(rb'<uniqueid[^>]*type=["\']tmdb["\'][^>]*>\s*(\d+)\s*<', re.I),
           re.compile(rb"<tmdbid>\s*(\d+)\s*<", re.I),
           re.compile(rb"themoviedb\.org/movie/(\d+)", re.I))

# folder poster shown unless the folder .nfo names another film than the current match
POSTER_EXPR = ("CASE WHEN art_poster IS NOT NULL AND (COALESCE(art_tmdb, 0) = 0 OR tmdb_id IS NULL "
               "OR art_tmdb = tmdb_id) THEN art_poster ELSE thumb END")


def read_nfo(media_path, entries=None):
    """-> (tmdb id or 0, written_by_us) for the .nfo of this movie; (None, False) when the folder can't be read."""
    d = os.path.dirname(media_path)
    stem = Path(media_path).stem
    if entries is None:
        try:
            entries = {e.lower(): e for e in os.listdir(d)}
        except OSError:
            return None, False
    for n in (stem + ".nfo", "movie.nfo"):
        e = entries.get(n.lower())
        if not e:
            continue
        try:
            with open(os.path.join(d, e), "rb") as f:
                data = f.read(65536)
        except OSError:
            return None, False
        own = any(m in data[:400] for m in OWN_MARKERS)
        for rx in _ID_RES:
            m = rx.search(data)
            if m:
                return int(m.group(1)), own
        return 0, own
    return 0, False


def nfo_tmdb(media_path):
    return read_nfo(media_path)[0]


def stale_own(media_path, tmdb_id, entries=None):
    """True when the folder's .nfo was written by this app for a different TMDB id than tmdb_id
    (so its poster.jpg / fanart.jpg / .nfo are leftovers of an old match and may be replaced)."""
    if not tmdb_id:
        return False
    tid, own = read_nfo(media_path, entries)
    return bool(own and tid and tid != tmdb_id)


def apply(c=None, ids=None, library_id=None):
    """Recompute items.poster for movies with folder art. Returns the number of rows looked at."""
    sql = "UPDATE items SET poster=" + POSTER_EXPR + " WHERE kind='movie' AND art_poster IS NOT NULL"
    args = []
    if ids is not None:
        ids = list(ids)
        if not ids:
            return 0
        sql += " AND id IN (%s)" % ",".join("?" * len(ids))
        args += ids
    if library_id is not None:
        sql += " AND library_id=?"
        args.append(library_id)
    if c is not None:
        return c.execute(sql, args).rowcount
    with db.tx() as c2:
        return c2.execute(sql, args).rowcount


def refresh(ids, rethumb=False):
    """Re-read the folder .nfo (and, with rethumb, the folder poster itself) for these movie items, then apply()."""
    ids = list(ids or [])
    if not ids:
        return 0
    rows = db.rows("SELECT id, path, poster, thumb, art_poster, art_tmdb FROM items WHERE kind='movie' AND id IN (%s)"
                   % ",".join("?" * len(ids)), ids)
    upd = []
    for r in rows:
        tid = nfo_tmdb(r["path"])
        if rethumb:
            img = media.find_local_image(Path(r["path"]))
            ap = media.make_image_thumb(img) if img else None
            if img and not ap:
                ap = r["art_poster"]
        else:
            ap = r["art_poster"] or (r["poster"] if r["poster"] and r["poster"] != r["thumb"] else None)
        upd.append((ap, tid if tid is not None else r["art_tmdb"], r["id"]))
    with db.tx() as c:
        c.executemany("UPDATE items SET art_poster=?, art_tmdb=? WHERE id=?", upd)
        apply(c, ids)
    return len(upd)


def _online(lib):
    if not lib["share_id"]:
        return True
    try:
        from . import sharehealth
        return (sharehealth.get(lib) or {}).get("state") == "online"
    except Exception:
        return False


def backfill(stop=lambda: False, batch=200, wait_s=120):
    """One pass over movies whose folder art was never checked (libraries from before 1.7.3).
    Only reads small .nfo files; never writes to a share.  Skips libraries whose share is not online."""
    done = 0
    t_end = time.time() + wait_s
    for lib in db.rows("SELECT id, share_id FROM libraries WHERE kind='movies'"):
        while lib["share_id"] and not _online(lib) and time.time() < t_end and not stop():
            time.sleep(5)          # share health needs a moment after startup
        if stop() or not _online(lib):
            continue
        while not stop():
            ids = [r["id"] for r in db.rows(
                "SELECT id FROM items WHERE library_id=? AND kind='movie' AND art_tmdb IS NULL AND "
                "(art_poster IS NOT NULL OR (poster IS NOT NULL AND poster IS NOT thumb)) LIMIT ?", (lib["id"], batch))]
            if not ids:
                break
            refresh(ids)
            # rows whose folder could not be read keep art_tmdb NULL: mark 0 so the pass ends (next start retries)
            with db.tx() as c:
                c.execute("UPDATE items SET art_tmdb=0 WHERE art_tmdb IS NULL AND id IN (%s)" % ",".join("?" * len(ids)), ids)
            done += len(ids)
    if done:
        n = db.row("SELECT COUNT(*) n FROM items WHERE kind='movie' AND art_poster IS NOT NULL AND poster IS NOT art_poster")
        log.info("folder art checked for %d movies; %d folder posters belong to another film and are not shown",
                 done, n["n"] if n else 0)
    return done


def start_backfill(stop=lambda: False):
    def run():
        try:
            backfill(stop)
        except Exception:
            log.exception("folder art backfill")
    threading.Thread(target=run, daemon=True, name="folderart-backfill").start()
