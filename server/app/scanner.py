"""Library scanner: walk folders, ffprobe new/changed files, make thumbnails, prune deleted files."""
import json
import logging
import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

from . import db, folderart, media

log = logging.getLogger("media-server.scan")

status = {}            # library_id -> dict (live progress, served by /api/activity)
logs = {}              # library_id -> deque of recent log lines for the Scans panel
_lock = threading.Lock()
_queue = []
_cv = threading.Condition(_lock)
_worker = None
_stop = False

BATCH_ROWS = 20        # commit at most this many items per transaction ...
BATCH_SECS = 1.0       # ... or at least this often, so new items show up while the scan runs
TMDB_KICK_SECS = 30    # start TMDB matching for newly added titles this often during a scan


def _workers():
    try:
        n = int(os.environ.get("MS_SCAN_WORKERS", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        n = max(2, min(4, (os.cpu_count() or 2) // 2))
    return min(n, 16)


def scan_log(library_id, msg, level=logging.INFO, journal=True):
    """Log to the journal and keep the line for the UI's scan activity panel."""
    d = logs.get(library_id)
    if d is None:
        d = logs[library_id] = deque(maxlen=300)
    d.append({"t": time.time(), "level": logging.getLevelName(level).lower(), "msg": msg})
    if journal:
        log.log(level, "library %s: %s", library_id, msg)


def request_scan(library_id: int, full=False):
    """Queue a scan (no-op if already queued/running)."""
    global _worker
    with _cv:
        st = status.get(library_id)
        if st and st.get("state") in ("queued", "scanning"):
            return False
        status[library_id] = {"state": "queued", "full": full, "queued_at": time.time()}
        _queue.append((library_id, full))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="scanner", daemon=True)
            _worker.start()
        _cv.notify()
    return True


def cancel_scan(library_id: int):
    """Stop a queued or running scan. Items already added stay; nothing is removed."""
    with _cv:
        st = status.get(library_id) or {}
        if st.get("state") == "queued":
            _queue[:] = [q for q in _queue if q[0] != library_id]
            status[library_id] = {"state": "cancelled", "finished_at": time.time(), "added": 0, "updated": 0,
                                  "removed": 0, "errors": 0}
            scan_log(library_id, "queued scan cancelled")
            return True
        if st.get("state") == "scanning":
            st["cancel"] = True
            st["phase_detail"] = "cancelling -- finishing the files in progress"
            scan_log(library_id, "cancel requested")
            return True
    return False


def _run():
    while not _stop:
        with _cv:
            while not _queue and not _stop:
                _cv.wait(timeout=5)
            if _stop:
                return
            lib_id, full = _queue.pop(0)
        try:
            scan_library(lib_id, full=full)
        except Exception as e:  # never kill the worker
            log.exception("scan of library %s failed", lib_id)
            st = status.get(lib_id) or {}
            st.update({"state": "error", "error": str(e), "finished_at": time.time()})
            status[lib_id] = st
            scan_log(lib_id, "scan failed: %s" % e, logging.ERROR)


def _exts_for(kind):
    if kind == "music":
        return media.AUDIO_EXT
    if kind == "mixed":
        return media.AUDIO_EXT | media.VIDEO_EXT
    return media.VIDEO_EXT


def _update_rate(st):
    """Files per minute over the last ~60 s, and an ETA once the total is known."""
    now = time.time()
    samples = st.setdefault("_samples", [])
    samples.append((now, st["done"]))
    while len(samples) > 2 and now - samples[0][0] > 60:
        samples.pop(0)
    t0, d0 = samples[0]
    if now - t0 >= 3 and st["done"] > d0:
        rate = (st["done"] - d0) / (now - t0)
    elif st["done"] and st.get("processing_since"):
        rate = st["done"] / max(1.0, now - st["processing_since"])
    else:
        rate = 0
    st["rate_per_min"] = round(rate * 60, 1)
    left = st["total"] - st["done"]
    st["eta_s"] = int(left / rate) if rate > 0 and left > 0 else (0 if left <= 0 and st["walk_done"] else None)


def scan_library(library_id: int, full=False):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (library_id,))
    if not lib:
        status.pop(library_id, None)
        return
    root = Path(lib["path"])
    nworkers = _workers()
    st = {"state": "scanning", "phase": "discovering", "full": full, "library": lib["name"],
          "started_at": time.time(), "found": 0, "dirs": 0, "unchanged": 0, "total": 0, "done": 0,
          "added": 0, "updated": 0, "removed": 0, "errors": 0, "walk_done": False, "current": [],
          "workers": nworkers, "rate_per_min": 0, "eta_s": None, "last_error": None}
    status[library_id] = st
    logs[library_id] = deque(maxlen=300)
    scan_log(library_id, "%s started (%s, %d workers)" % ("full rescan" if full else "scan", root, nworkers))

    if not root.is_dir():
        _finish(lib, st, "error", "Folder not found or not mounted: %s" % root)
        return
    try:
        next(os.scandir(root), None)
    except OSError as e:
        _finish(lib, st, "error", "Cannot read %s: %s" % (root, e))
        return

    existing = {r["path"]: r for r in db.rows("SELECT id,path,size,mtime,probed FROM items WHERE library_id=?",
                                              (library_id,))}
    exts = _exts_for(lib["kind"])
    seen = set()
    jobs = queue.Queue()
    results = queue.Queue()
    STOP = object()
    walk_error = []

    def cancelled():
        return st.get("cancel") or _stop

    # --- 1. walk the tree (own thread) and hand changed/new files to the workers as soon as they are found
    def walker():
        def onerror(e):
            st["errors"] += 1
            st["walk_errors"] = st.get("walk_errors", 0) + 1
            st["last_error"] = "Cannot read folder %s: %s" % (getattr(e, "filename", "?"), e.strerror or e)
            scan_log(library_id, st["last_error"], logging.WARNING)
        try:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=True, onerror=onerror):
                if cancelled():
                    break
                st["dirs"] += 1
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in media.SKIP_DIRS)
                for fn in sorted(filenames):
                    if fn.startswith("."):
                        continue
                    if os.path.splitext(fn)[1].lower() not in exts:
                        continue
                    f = os.path.join(dirpath, fn)
                    try:
                        s = os.stat(f)
                    except OSError:
                        continue
                    seen.add(f)
                    st["found"] += 1
                    old = existing.get(f)
                    if (full or not old or old["size"] != s.st_size or abs((old["mtime"] or 0) - s.st_mtime) > 1
                            or old["probed"] == 0):   # -1 = ffprobe failed before: retried on change / full rescan
                        st["total"] += 1
                        jobs.put((f, s.st_size, s.st_mtime, old["id"] if old else None))
                    else:
                        st["unchanged"] += 1
        except Exception as e:  # noqa -- reported, and pruning is skipped
            walk_error.append(e)
            log.exception("walk failed")
        finally:
            st["walk_done"] = True
            for _ in range(nworkers):
                jobs.put(STOP)

    # --- 2. bounded pool: ffprobe + thumbnails, at most `nworkers` ffmpeg processes at a time
    def worker():
        while True:
            t = jobs.get()
            if t is STOP:
                results.put(STOP)
                return
            if cancelled():
                continue
            name = os.path.basename(t[0])
            st["current"].append(name)
            try:
                info = build_item(lib, root, Path(t[0]), t[1], t[2])
                err = None
            except Exception as e:  # noqa
                info, err = None, str(e)
            finally:
                try:
                    st["current"].remove(name)
                except ValueError:
                    pass
            results.put((t, info, err))

    threading.Thread(target=walker, daemon=True, name="scan-walk").start()
    for i in range(nworkers):
        threading.Thread(target=worker, daemon=True, name="scan-w%d" % i).start()

    # --- 3. this thread: commit results in small batches so the UI can show items while the scan runs
    pending = []
    last_commit = last_kick = time.time()
    added_since_kick = 0
    stopped = 0

    def commit():
        nonlocal pending
        if not pending:
            return
        now = int(time.time())
        with db.tx() as c:
            for (f, size, mtime, old_id), info in pending:
                cols = sorted(info.keys())
                if old_id:
                    ms = c.execute("SELECT meta_status FROM items WHERE id=?", (old_id,)).fetchone()
                    if ms and ms[0] in ("matched", "manual"):   # keep sorting by the TMDB title
                        cols = [k for k in cols if k != "sort_title"]
                    c.execute("UPDATE items SET %s WHERE id=?" % ",".join("%s=?" % k for k in cols),
                              [info[k] for k in cols] + [old_id])
                else:
                    c.execute("INSERT INTO items(library_id,path,added_at,%s) VALUES(?,?,?,%s)"
                              % (",".join(cols), ",".join("?" * len(cols))),
                              [library_id, f, now] + [info[k] for k in cols])
        pending = []

    while stopped < nworkers:
        try:
            r = results.get(timeout=0.5)
        except queue.Empty:
            r = None
        if r is STOP:
            stopped += 1
        elif r is not None:
            (f, size, mtime, old_id), info, err = r
            st["done"] += 1
            st.setdefault("processing_since", time.time())
            if info is None:
                st["errors"] += 1
                st["last_error"] = "%s: %s" % (os.path.basename(f), err)
                scan_log(library_id, "failed: %s (%s)" % (f, err), logging.WARNING)
            else:
                pending.append(((f, size, mtime, old_id), info))
                if old_id:
                    st["updated"] += 1
                    scan_log(library_id, "updated: %s" % os.path.relpath(f, root), journal=False)
                else:
                    st["added"] += 1
                    added_since_kick += 1
                    scan_log(library_id, "added: %s" % os.path.relpath(f, root), journal=False)
                if info.get("probed") != 1:
                    st["errors"] += 1
                    st["last_error"] = "could not read media info: %s" % os.path.basename(f)
                    scan_log(library_id, "could not read media info (ffprobe) -- added without details: %s"
                             % os.path.relpath(f, root), logging.WARNING, journal=False)
        if st["walk_done"] and st["phase"] == "discovering":
            st["phase"] = "processing"
            scan_log(library_id, "found %d media files in %d folders: %d new/changed, %d unchanged"
                     % (st["found"], st["dirs"], st["total"], st["unchanged"]))
        elif st["phase"] == "discovering" and st["done"]:
            st["phase_detail"] = "still discovering files while processing"
        now = time.time()
        if len(pending) >= BATCH_ROWS or (pending and now - last_commit >= BATCH_SECS):
            commit()
            last_commit = now
        _update_rate(st)
        if added_since_kick and now - last_kick >= TMDB_KICK_SECS and lib["kind"] in ("movies", "tv"):
            commit()
            last_kick = now
            added_since_kick = 0
            _kick_tmdb(library_id)
    commit()
    st["current"] = []

    if cancelled():
        _finish(lib, st, "cancelled", None)
        return
    if walk_error:
        _finish(lib, st, "error", "Scan stopped while reading folders: %s" % walk_error[0])
        return
    if not seen and existing:
        # an empty walk of a library that had items almost always means the share dropped -- keep the items
        _finish(lib, st, "error", "No media found in %s (share offline?). Existing items kept." % root)
        return
    st["phase"] = "cleanup"
    gone = set(existing) - seen
    if gone and st.get("walk_errors"):
        scan_log(library_id, "%d folder(s) could not be read, so %d missing item(s) were kept this time"
                 % (st["walk_errors"], len(gone)), logging.WARNING)
        gone = set()
    if gone:
        with db.tx() as c:
            for p in gone:
                c.execute("DELETE FROM items WHERE library_id=? AND path=?", (library_id, p))
        st["removed"] = len(gone)
        scan_log(library_id, "removed %d items whose files are gone" % len(gone))
    _finish(lib, st, "done", None)


def _kick_tmdb(library_id):
    try:
        from . import tmdb
        tmdb.queue_library(library_id)
    except Exception:
        log.exception("could not queue TMDB metadata")


def _finish(lib, st, state, error):
    st["state"] = state
    st["phase"] = "done"
    st.pop("phase_detail", None)
    st.pop("_samples", None)
    st["finished_at"] = time.time()
    st["current"] = []
    st["eta_s"] = None
    if error:
        st["error"] = error
        st["last_error"] = error
    summary = error or "%sadded %d, updated %d, removed %d, errors %d" % (
        "cancelled: " if state == "cancelled" else "",
        st.get("added", 0), st.get("updated", 0), st.get("removed", 0), st.get("errors", 0))
    st["summary"] = summary
    with db.tx() as c:
        c.execute("UPDATE libraries SET last_scan=?, last_scan_result=? WHERE id=?",
                  (int(time.time()), summary, lib["id"]))
    scan_log(lib["id"], "scan %s in %ds: %s" % (state, st["finished_at"] - st.get("started_at", st["finished_at"]), summary),
             logging.WARNING if state == "error" else logging.INFO)
    if lib["kind"] == "movies":
        try:      # 1.7.3: a folder poster whose .nfo names another film than the match is not shown
            folderart.apply(library_id=lib["id"])
        except Exception:
            log.exception("folder art")
    if state in ("done", "cancelled") and lib["kind"] in ("movies", "tv"):
        _kick_tmdb(lib["id"])
    if state == "done" and lib["kind"] in ("movies", "tv", "other"):
        try:
            from . import preload
            preload.enqueue_library(lib["id"])
        except Exception:
            log.exception("preload enqueue")


def build_item(lib, root: Path, path: Path, size, mtime):
    kind = lib["kind"]
    ext = path.suffix.lower()
    is_audio = ext in media.AUDIO_EXT
    probe = media.summarize_probe(media.ffprobe(str(path)))
    tags = probe.pop("tags", {}) if probe else {}
    has_cover = probe.pop("has_cover", False) if probe else False
    if probe and not probe.get("vcodec") and probe.get("acodec"):
        is_audio = True

    if is_audio:
        info = media.parse_track(path, root)
        info = media.apply_audio_tags(info, tags)
        info["media_type"] = "audio"
    elif kind == "tv":
        info = media.parse_episode(path, root)
        info["media_type"] = "video"
    elif kind == "movies":
        info = media.parse_movie(path)
        info["media_type"] = "video"
    else:
        info = media.parse_movie(path)
        info["kind"] = "video"
        info["media_type"] = "video"

    info.update({k: v for k, v in (probe or {}).items()})
    info["probed"] = 1 if probe else -1
    info["size"] = size
    info["mtime"] = mtime
    info["sort_title"] = media.sort_key(info.get("title"))
    info.setdefault("external_subs", None)

    # artwork
    thumb = poster = None
    if is_audio:
        img = media.find_local_image(path, names=("cover", "folder", "front", "album"), include_stem=False)
        if img:
            poster = media.make_image_thumb(img)
        if not poster and has_cover:
            poster = media.make_cover_thumb(str(path))
        thumb = poster
    else:
        thumb = media.make_video_thumb(str(path), info.get("duration")) if probe else None
        if info.get("kind") == "episode":
            # show poster from the show folder
            try:
                show_dir = root / path.relative_to(root).parts[0]
            except (ValueError, IndexError):
                show_dir = path.parent
            img = media.find_local_image(show_dir / "x", include_stem=False)
            if not img and path.parent != show_dir:
                img = media.find_local_image(path.parent / "x", include_stem=False)
            if img:
                poster = media.make_image_thumb(img)
            ep_img = media.find_local_image(path, names=(), include_stem=True)
            if ep_img:
                thumb = media.make_image_thumb(ep_img) or thumb
        else:
            img = media.find_local_image(path)
            if img:
                poster = media.make_image_thumb(img)
            if info.get("kind") == "movie":      # 1.7.3: remember the folder poster + the film its .nfo names
                info["art_poster"] = poster
                info["art_tmdb"] = folderart.nfo_tmdb(str(path)) if poster else 0
        subs = media.find_external_subs(path)
        info["external_subs"] = json.dumps(subs) if subs else None
    info["thumb"] = thumb
    info["poster"] = poster or thumb
    allowed = {"media_type", "kind", "title", "sort_title", "edition", "file_title", "year", "show", "season", "episode", "episode_title",
               "artist", "album", "album_artist", "track", "disc", "genre", "duration", "container", "vcodec",
               "acodec", "width", "height", "bitrate", "pix_fmt", "audio_streams", "subtitle_streams",
               "external_subs", "size", "mtime", "thumb", "poster", "probed", "art_poster", "art_tmdb",
               "rotation", "color_transfer"}
    return {k: v for k, v in info.items() if k in allowed}


def scheduler_tick(now=None):
    """Queue a scan for every library whose interval (off / 1 / 6 / 24 h) has passed. Returns the ids queued."""
    now = now or time.time()
    due = []
    for lib in db.rows("SELECT id, scan_interval_h, last_scan FROM libraries"):
        h = lib["scan_interval_h"] or 0
        if h > 0 and (not lib["last_scan"] or now - lib["last_scan"] >= h * 3600):
            st = status.get(lib["id"]) or {}
            if st.get("state") in ("scanning", "queued"):
                continue
            request_scan(lib["id"])
            due.append(lib["id"])
    return due


def scheduler_loop():
    """In-process scheduler: checks every minute (no cron/systemd timer needed)."""
    while not _stop:
        try:
            due = scheduler_tick()
            if due:
                log.info("scheduled scan for libraries %s", due)
        except Exception:
            log.exception("scheduler")
        for _ in range(12):
            if _stop:
                return
            time.sleep(5)
