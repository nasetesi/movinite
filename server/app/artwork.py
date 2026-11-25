"""1.3: save artwork (poster.jpg, fanart.jpg) and a Kodi/Jellyfin/Plex-style .nfo next to movie files.

Opt-in per library (Settings -> Libraries -> Artwork), and the share must be allowed to write
(Settings -> Shares -> "Allow writing (artwork only)"). Rules:
  * never overwrite an existing poster / fanart / .nfo unless the library's "overwrite" option is on
    (and even then only the files this feature names -- poster.jpg, fanart.jpg, movie.nfo / <name>-poster.jpg ...)
  * a folder holding exactly ONE movie (possibly split in cd1/cd2 files) gets poster.jpg / fanart.jpg / movie.nfo;
    files sitting loose next to other movies (or in the library root) get <filename>-poster.jpg /
    <filename>-fanart.jpg / <filename>.nfo, so nothing is shared between movies
  * new files are created with O_EXCL (no race, no clobbering), mode 0644; existing files keep their owner
    (overwrite rewrites them in place instead of replacing the inode)
  * a dry run returns exactly the list of files that would be written
"""
import errno
import json
import logging
import os
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config, db, media, settings, tmdb

log = logging.getLogger("media-server.artwork")

POSTER_NAMES = ("poster", "folder", "cover", "movie", "default")
FANART_NAMES = ("fanart", "backdrop", "background", "art")
status = {}          # library_id -> {state, phase, total, done, written, skipped, errors, last_error, dry}
_lock = threading.Lock()
_queue = []          # (library_id, [item ids]) from automatic matching
_qcond = threading.Condition()
_worker = None
_cancel = set()


class WriteDenied(Exception):
    pass


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
def _exists_ci(d, names, entries):
    for n in names:
        if n.lower() in entries:
            return entries[n.lower()]
    return None


def _image_names(base_names, stem=None):
    out = []
    for b in base_names:
        for ext in media.IMAGE_EXT:
            out.append((stem + "-" + b if stem else b) + ext)
    return out


def folder_mode(item, lib_root, siblings):
    """'folder' when the item's directory holds only this movie (and no nested movies), else 'file'."""
    d = os.path.dirname(item["path"])
    if os.path.normpath(d) == os.path.normpath(lib_root):
        return "file"
    others = [s for s in siblings.get(d, []) if s["id"] != item["id"]]
    for s in others:
        # same movie = same title + year from the file names (cd1/cd2, 1080p + 4K, cut + theatrical), and not
        # matched to different TMDB films. Two different files that ended up on one TMDB id still count as two.
        same = media.sort_key(s.get("title") or "") == media.sort_key(item.get("title") or "") and s.get("year") == item.get("year")
        if same and item.get("tmdb_id") and s.get("tmdb_id") and s.get("tmdb_id") != item.get("tmdb_id"):
            same = False
        if not same:
            return "file"
    return "folder"


def plan_item(item, lib, meta, siblings, nested_dirs):
    """-> list of {"path", "what": poster|fanart|nfo, "action": create|overwrite|skip, "reason"}"""
    d = os.path.dirname(item["path"])
    stem = Path(item["path"]).stem
    mode = folder_mode(item, lib["path"], siblings)
    if mode == "folder" and d in nested_dirs:
        mode = "file"      # e.g. "Action/" holding one movie plus sub-folders of other movies
    try:
        entries = {e.lower(): e for e in os.listdir(d)}
    except OSError as e:
        return [{"path": d, "what": "folder", "action": "skip", "reason": "folder not readable: %s" % e.strerror}]
    out = []
    want = [("poster", bool(meta and (meta.get("poster_path") or meta.get("poster"))))]
    if lib.get("art_fanart"):
        want.append(("fanart", bool(meta and (meta.get("backdrop_path") or meta.get("backdrop")))))
    if lib.get("art_nfo"):
        want.append(("nfo", bool(meta)))
    for what, available in want:
        if what == "nfo":
            target = "movie.nfo" if mode == "folder" else stem + ".nfo"
            existing = _exists_ci(d, [stem + ".nfo"] + (["movie.nfo"] if mode == "folder" else []), entries)
        else:
            base = POSTER_NAMES if what == "poster" else FANART_NAMES
            target = (what + ".jpg") if mode == "folder" else (stem + "-" + what + ".jpg")
            names = _image_names(base[:1] if what == "fanart" and mode == "file" else base, stem) + \
                (_image_names(base) if mode == "folder" else [])
            if what == "poster":
                names = [stem + ext for ext in media.IMAGE_EXT] + names
            existing = _exists_ci(d, names, entries)
        path = os.path.join(d, target)
        if not available:
            out.append({"path": path, "what": what, "action": "skip", "reason": "no TMDB %s" % what})
        elif existing and not (lib.get("art_overwrite") and existing.lower() == target.lower()):
            out.append({"path": os.path.join(d, existing), "what": what, "action": "skip",
                        "reason": "already there" if existing.lower() == target.lower() else "existing %s" % existing})
        else:
            out.append({"path": path, "what": what, "action": "overwrite" if existing else "create",
                        "reason": None, "mode": mode})
    return out


def _library_items(lib_id, item_ids=None):
    q = ("SELECT id, path, title, year, tmdb_id, edition, meta_status FROM items WHERE library_id=? AND kind='movie' "
         "AND meta_status IN ('matched','manual') AND tmdb_id IS NOT NULL")
    args = [lib_id]
    if item_ids:
        q += " AND id IN (%s)" % ",".join("?" * len(item_ids))
        args += list(item_ids)
    return db.rows(q + " ORDER BY path", args)


def _siblings(lib_id):
    sib, nested = {}, set()
    for r in db.rows("SELECT id, path, title, year, tmdb_id FROM items WHERE library_id=? AND media_type='video'", (lib_id,)):
        d = os.path.dirname(r["path"])
        sib.setdefault(d, []).append(r)
    dirs = sorted(sib)
    for d in dirs:
        p = os.path.dirname(d)
        while p and p != os.path.dirname(p):
            if p in sib:
                nested.add(p)
            p = os.path.dirname(p)
    return sib, nested


def plan_library(lib_id, item_ids=None, limit=None):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise ValueError("No such library")
    sib, nested = _siblings(lib_id)
    actions = []
    for it in _library_items(lib_id, item_ids):
        meta = tmdb.cached("movie", it["tmdb_id"])
        for a in plan_item(it, lib, meta, sib, nested):
            a["item_id"] = it["id"]
            a["title"] = (meta or {}).get("title") or it["title"]
            actions.append(a)
        if limit and len(actions) >= limit:
            break
    return lib, actions


def summarize(actions):
    s = {"create": 0, "overwrite": 0, "skip": 0}
    for a in actions:
        s[a["action"]] = s.get(a["action"], 0) + 1
    return s


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def nfo_xml(meta, item):
    """Kodi movie .nfo (also read by Jellyfin / Emby, and Plex with the XBMCnfoMoviesImporter agent)."""
    root = ET.Element("movie")

    def sub(tag, text, **attrs):
        if text is None or text == "":
            return None
        e = ET.SubElement(root, tag, **attrs)
        e.text = str(text)
        return e
    sub("title", meta.get("title"))
    if meta.get("original_title") and meta.get("original_title") != meta.get("title"):
        sub("originaltitle", meta.get("original_title"))
    sub("year", meta.get("year"))
    sub("premiered", meta.get("release_date"))
    sub("plot", meta.get("overview"))
    sub("outline", (meta.get("overview") or "").split(". ")[0][:300] or None)
    sub("tagline", meta.get("tagline"))
    sub("runtime", meta.get("runtime"))
    if meta.get("rating") is not None:
        ratings = ET.SubElement(root, "ratings")
        r = ET.SubElement(ratings, "rating", name="themoviedb", max="10", default="true")
        ET.SubElement(r, "value").text = "%.1f" % float(meta["rating"])
        ET.SubElement(r, "votes").text = str(meta.get("vote_count") or 0)
    for g in json.loads(meta.get("genres") or "[]"):
        sub("genre", g)
    extra = json.loads(meta.get("extra") or "{}")
    for st in extra.get("studios") or []:
        sub("studio", st)
    for c in extra.get("countries") or []:
        sub("country", c)
    if extra.get("collection"):
        st = ET.SubElement(root, "set")
        ET.SubElement(st, "name").text = extra["collection"]
    sub("uniqueid", meta["tmdb_id"], type="tmdb", default="true")
    if meta.get("imdb_id"):
        sub("uniqueid", meta["imdb_id"], type="imdb")
        sub("imdbid", meta["imdb_id"])
    sub("tmdbid", meta["tmdb_id"])
    if item.get("edition"):
        sub("edition", item["edition"])       # Kodi 21+ / Jellyfin
    if meta.get("poster_path"):
        sub("thumb", tmdb.image_url(meta["poster_path"], "original"), aspect="poster")
    if meta.get("backdrop_path"):
        fa = ET.SubElement(root, "fanart")
        ET.SubElement(fa, "thumb").text = tmdb.image_url(meta["backdrop_path"], "original")
    ET.indent(root, space="  ")
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            b"<!-- written by Movinite from TMDB (themoviedb.org) -->\n" + ET.tostring(root, encoding="utf-8") + b"\n")


def _image_bytes(path_or_name, size):
    """bytes of a TMDB image: full-size from TMDB if we know its path, else the cached copy."""
    if path_or_name and path_or_name.startswith("/"):
        url = tmdb.image_url(path_or_name, size)
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": tmdb.USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read(25 * 1024 * 1024)
                if data:
                    return data
            except Exception:
                time.sleep(1 + attempt)
        return None
    p = config.THUMB_DIR / (path_or_name or "")
    return p.read_bytes() if path_or_name and p.is_file() else None


def _write(path, data, overwrite):
    """Create path with O_EXCL (or rewrite in place when overwriting). Raises WriteDenied on EROFS/EACCES."""
    try:
        if overwrite and os.path.exists(path):
            with open(path, "r+b") as f:        # same inode: keeps owner/group/permissions of the existing file
                f.write(data)
                f.truncate()
            return "overwritten"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except BaseException:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
        return "created"
    except FileExistsError:
        return "exists"
    except OSError as e:
        if e.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise WriteDenied(e.errno, os.path.dirname(path)) from e
        raise


def denied_message(e, lib):
    code, folder = e.args[0], e.args[1]
    if code == errno.EROFS:
        share = lib.get("share_id")
        return ("The library is on a read-only mount. Turn on \"Allow writing (artwork only)\" for its share in "
                "Settings -> Libraries -> Artwork%s." % ("" if share else " (or make the local folder writable)"))
    return ("The server refused to write in %s (permission denied). Check that the share's user can write there "
            "(NAS share permissions / ACLs), or for local folders that the 'media-server' user can." % folder)


def check_writable(lib):
    """Try to create and delete a hidden test file in the library root. -> (ok, message)"""
    root = lib["path"]
    if not os.path.isdir(root):
        return False, "The library folder is not reachable: %s" % root
    test = os.path.join(root, ".media-server-write-test-%d" % os.getpid())
    try:
        _write(test, b"test", False)
        os.unlink(test)
        return True, "ok"
    except WriteDenied as e:
        return False, denied_message(e, lib)
    except OSError as e:
        return False, "Could not write in %s: %s" % (root, e.strerror or e)


def _meta_full(tmdb_id):
    m = tmdb.cached("movie", tmdb_id)
    if m and not m.get("poster_path") and m.get("fetched_at"):
        try:       # cached before 1.3: fetch again for the full-size image paths + IMDb id
            tmdb.fetch_details("movie", tmdb_id, force=True)
            m = tmdb.cached("movie", tmdb_id)
        except tmdb.TMDBError:
            pass
    return m


def run_library(lib_id, item_ids=None, dry_run=False, auto=False):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        return
    st = {"state": "running", "phase": "planning", "total": 0, "done": 0, "written": 0, "skipped": 0, "errors": 0,
          "started_at": time.time(), "auto": auto}
    with _lock:
        status[lib_id] = st
    _cancel.discard(lib_id)
    try:
        ok, msg = check_writable(lib)
        if not ok:
            st.update(state="error", error=msg, finished_at=time.time())
            log.warning("artwork library %s: %s", lib_id, msg)
            return
        sib, nested = _siblings(lib_id)
        items = _library_items(lib_id, item_ids)
        st.update(phase="writing", total=len(items))
        for it in items:
            if lib_id in _cancel:
                st.update(state="cancelled", finished_at=time.time())
                return
            meta = _meta_full(it["tmdb_id"])
            for a in plan_item(it, lib, meta, sib, nested):
                if a["action"] == "skip":
                    st["skipped"] += 1
                    continue
                if a["what"] == "nfo":
                    data = nfo_xml(meta, it)
                elif a["what"] == "poster":
                    data = _image_bytes(meta.get("poster_path"), "w780") or _image_bytes(meta.get("poster"), None)
                else:
                    data = _image_bytes(meta.get("backdrop_path"), "w1280") or _image_bytes(meta.get("backdrop"), None)
                if not data:
                    st["errors"] += 1
                    st["last_error"] = "could not download %s for %s" % (a["what"], it["title"])
                    continue
                try:
                    r = _write(a["path"], data, a["action"] == "overwrite")
                except WriteDenied as e:
                    st.update(state="error", error=denied_message(e, lib), finished_at=time.time())
                    log.warning("artwork library %s stopped: %s", lib_id, st["error"])
                    return
                except OSError as e:
                    st["errors"] += 1
                    st["last_error"] = "%s: %s" % (os.path.basename(a["path"]), e.strerror or e)
                    continue
                if r == "exists":
                    st["skipped"] += 1
                else:
                    st["written"] += 1
            st["done"] += 1
        st.update(state="done", finished_at=time.time())
        log.info("artwork library %s: %s", lib_id, {k: st[k] for k in ("total", "written", "skipped", "errors")})
    except Exception as e:
        log.exception("artwork library %s", lib_id)
        st.update(state="error", error=str(e), finished_at=time.time())


def start_library(lib_id, item_ids=None):
    st = status.get(lib_id) or {}
    if st.get("state") == "running":
        return False
    status[lib_id] = {"state": "queued", "total": 0, "done": 0, "written": 0, "skipped": 0, "errors": 0}
    threading.Thread(target=run_library, args=(lib_id, item_ids), daemon=True, name="artwork-%d" % lib_id).start()
    return True


def cancel(lib_id):
    _cancel.add(lib_id)


# ---- automatic: new matches in libraries with artwork saving on
def _on_matched(library_id, item_ids):
    lib = db.row("SELECT art_write FROM libraries WHERE id=?", (library_id,))
    if not lib or not lib["art_write"]:
        return
    with _qcond:
        _queue.append((library_id, list(item_ids)))
        _qcond.notify()
    _ensure_worker()


def _ensure_worker():
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_auto_loop, daemon=True, name="artwork-auto")
            _worker.start()


def _auto_loop():
    while True:
        with _qcond:
            while not _queue:
                _qcond.wait(30)
            time.sleep(0)
            batch = {}
            while _queue:
                lid, ids = _queue.pop(0)
                batch.setdefault(lid, []).extend(ids)
        time.sleep(2)            # let a burst of matches collect
        with _qcond:
            while _queue:
                lid, ids = _queue.pop(0)
                batch.setdefault(lid, []).extend(ids)
        later = []
        for lid, ids in batch.items():
            st = status.get(lid) or {}
            if st.get("state") in ("running", "queued"):
                later.append((lid, ids))   # try again once that run is over (it may not include these)
                continue
            if st.get("state") == "error" and time.time() - (st.get("finished_at") or 0) < 600:
                continue         # don't hammer a read-only share
            run_library(lid, ids, auto=True)
        if later:
            time.sleep(10)
            with _qcond:
                _queue.extend(later)


tmdb.on_matched = _on_matched
