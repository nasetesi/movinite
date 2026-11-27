"""1.7.9 / 2.2: low-priority start caches — subtitles, remux cut points, opening clips,
colour tags, and trickplay sprites.

All heavy work runs on a single background thread, only while nobody is streaming, and is
throttled so the NAS is not kept busy. Play requests never wait for this thread: they use
what is already cached, or (for subtitles) get a 202 and retry.
"""
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import config, db, transcode

log = logging.getLogger("media-server.preload")

PREFETCH_SEGS = 3                 # 3 × 2s = the first ~6 seconds
PREFETCH_PROFILE = "1080p"
DEFAULT_CACHE_GB = 2.0
TICK_S = 2.0
NAS_PAUSE_S = 0.6                 # breathe between items
BOUNDS_CHUNK = 40                 # remux interval seeks per ffprobe
SUB_RETRY_S = 900

_stop = False
_wake = threading.Event()
_lock = threading.Lock()
_urgent_subs = []                 # (item_dict, key) requested at play time
_worker = None
_job = {"kind": None, "proc": None}   # in-flight background ffmpeg/ffprobe


def cache_gb():
    try:
        from . import settings
        raw = settings.get("prefetch_cache_gb")
        if raw not in (None, ""):
            n = float(raw)
            if 0 <= n <= 100:
                return n
    except (TypeError, ValueError, Exception):
        pass
    return DEFAULT_CACHE_GB


def set_cache_gb(n):
    from . import settings
    n = float(n)
    if n < 0 or n > 100:
        raise ValueError("Opening-clip cache must be between 0 and 100 GB")
    settings.put("prefetch_cache_gb", str(n))
    evict_lru()


def busy():
    """True when a viewer is using a transcode/remux session (or one just started)."""
    now = time.time()
    for s in list(transcode._sessions.values()):
        if getattr(s, "destroyed", False):
            continue
        if s.running() or (now - (s.last_access or 0) < 20):
            return True
    return False


def first_segment_ready(item_id):
    for s in list(transcode._sessions.values()):
        if s.item.get("id") == item_id and s._ready(s.start_seg):
            return True
    return False


def start_loop(stop_flag):
    global _worker, _stop
    _stop = False

    def run():
        # give start-up (card detect, share mounts) a moment
        for _ in range(15):
            if stop_flag():
                return
            time.sleep(1)
        while not stop_flag():
            try:
                _tick()
            except Exception:
                log.exception("preload tick")
            _wake.wait(TICK_S)
            _wake.clear()

    _worker = threading.Thread(target=run, name="preload", daemon=True)
    _worker.start()
    return _worker


def kick():
    _wake.set()


def _register(kind, proc):
    with _lock:
        _job["kind"] = kind
        _job["proc"] = proc


def _clear(proc=None):
    with _lock:
        if proc is None or _job.get("proc") is proc:
            _job["kind"] = None
            _job["proc"] = None


def _stop_proc(p):
    if p is None:
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except Exception:
        try:
            p.terminate()
        except Exception:
            pass
    try:
        p.wait(timeout=3)
    except Exception:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass


def jobs():
    """What the status panel shows as background cache work (not viewer transcodes)."""
    with _lock:
        p = _job.get("proc")
        kind = _job.get("kind")
        running = bool(p is not None and p.poll() is None)
    if not running:
        kind = None
    return {"running": 1 if running else 0, "kind": kind}


def yield_to_playback():
    """1.8: stop an in-flight subtitle/prefetch/remux job the moment a stream starts.

    extract_sub used to run ffmpeg to completion even after someone pressed play,
    which kept the NAS busy and delayed the first picture (about 4.6s in the 1.7.9 install).
    """
    with _lock:
        p = _job.get("proc")
        kind = _job.get("kind")
    if p is not None and p.poll() is None:
        _stop_proc(p)
        log.info("preload yielded to playback (stopped %s pid %s)", kind, getattr(p, "pid", None))
    _clear(p)
    try:
        from . import offline
        offline.yield_now()       # 2.0: pause a download transcode too (it carries on when streaming is idle)
    except Exception:
        pass
    kick()


def run_cmd(cmd, timeout, kind="remux"):
    """Run a background ffprobe/ffmpeg that yield_to_playback can kill mid-flight."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    _register(kind, p)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        _stop_proc(p)
        raise
    finally:
        _clear(p)



def enqueue_library(library_id):
    """After a scan: queue subtitle extract, remux bounds, and opening clips for new/changed videos."""
    kick()


def _tick():
    # Urgent subtitles (a player is waiting) may run once the first video segment is out,
    # even if a stream is still active — but never alongside a just-started encode.
    if _urgent_subs:
        _drain_urgent_subs()
    if busy():
        return
    if _do_one_subtitle():
        time.sleep(NAS_PAUSE_S)
        return
    if _do_one_remux():
        time.sleep(NAS_PAUSE_S)
        return
    if _do_one_color():
        time.sleep(NAS_PAUSE_S)
        return
    if _do_one_hdr():
        time.sleep(NAS_PAUSE_S)
        return
    if cache_gb() <= 0:
        try:
            from . import trickplay
            if trickplay._do_one():
                time.sleep(NAS_PAUSE_S)
                return
        except Exception:
            log.exception("trickplay tick")
        try:
            from . import skipintro
            if skipintro._do_one():
                time.sleep(NAS_PAUSE_S)
        except Exception:
            log.exception("intro tick")
        return
    if _do_one_prefetch():
        evict_lru()
        time.sleep(NAS_PAUSE_S)
        return
    try:
        from . import trickplay
        if trickplay._do_one():
            time.sleep(NAS_PAUSE_S)
            return
    except Exception:
        log.exception("trickplay tick")
    try:
        from . import skipintro
        if skipintro._do_one():
            time.sleep(NAS_PAUSE_S)
    except Exception:
        log.exception("intro tick")


def _drain_urgent_subs():
    """fix/transcode-stuck: urgent subtitle requests now start one background pass per item
    (ensure_subs_async). Nothing waits here any more; this only hands queued items over."""
    with _lock:
        pending = list(_urgent_subs)
        _urgent_subs[:] = []
    seen = set()
    for item, _key in pending:
        if item.get("id") in seen:
            continue
        seen.add(item.get("id"))
        try:
            ensure_subs_async(item)
        except Exception:
            log.exception("urgent subtitle %s", item.get("id"))


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------
def sub_path(item_id, key):
    return config.SUBS_DIR / str(item_id) / ("%s.vtt" % key)


def sub_get(item, key):
    """Return a Path if a fresh VTT is cached, else None."""
    row = db.row("SELECT mtime, status, path FROM subtitle_cache WHERE item_id=? AND key=?",
                 (item["id"], key))
    if not row or row.get("status") != "ready":
        return None
    if row.get("mtime") != item.get("mtime"):
        return None
    p = config.DATA_DIR / row["path"] if row.get("path") and not str(row["path"]).startswith("/") else Path(row["path"] or "")
    if not p.is_file() or p.stat().st_size < 8:
        return None
    return p


def sub_enqueue(item, key, urgent=False):
    with db.tx() as c:
        c.execute("INSERT INTO subtitle_cache(item_id, key, mtime, status, checked_at, attempts) "
                  "VALUES(?,?,?,?,?,0) ON CONFLICT(item_id, key) DO UPDATE SET "
                  "mtime=excluded.mtime, status=CASE WHEN subtitle_cache.status='ready' AND "
                  "subtitle_cache.mtime=excluded.mtime THEN subtitle_cache.status ELSE 'pending' END",
                  (item["id"], key, item.get("mtime"), "pending", int(time.time())))
    if urgent:
        ensure_subs_async(item)
        kick()


def sub_cmd(item, key):
    if key.startswith("e") and key[1:].isdigit():
        ext_subs = json.loads(item.get("external_subs") or "[]")
        i = int(key[1:])
        if i >= len(ext_subs):
            return None
        src = os.path.join(os.path.dirname(item["path"]), ext_subs[i]["file"])
        return [config.FFMPEG, "-nostdin", "-loglevel", "error", "-i", src, "-f", "webvtt", "-"]
    if key.startswith("s") and key[1:].isdigit():
        return [config.FFMPEG, "-nostdin", "-loglevel", "error", "-i", item["path"],
                "-map", "0:%d" % int(key[1:]), "-f", "webvtt", "-"]
    return None


def extract_sub(item, key, timeout=None):
    """Extract one subtitle key. Embedded streams use the one-pass helper (one read of the
    file); sidecar files are small and converted on their own."""
    if key.startswith("s") and key[1:].isdigit():
        done = extract_item_subs(item, [key], timeout=timeout or SUB_PASS_TIMEOUT_S, yieldable=True)
        return key in done
    cmd = sub_cmd(item, key)
    if not cmd:
        _sub_status(item, key, "retry")
        return False
    dest = sub_path(item["id"], key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".vtt.tmp")
    p = None
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        _register("subtitles", p)
        try:
            out, err = p.communicate(timeout=timeout or SUB_SIDECAR_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _stop_proc(p)
            _sub_status(item, key, "retry")
            return False
        if p.returncode != 0:
            _sub_status(item, key, "retry")
            return False
        tmp.write_bytes(out or b"WEBVTT\n\n")
        tmp.replace(dest)
        rel = str(dest.relative_to(config.DATA_DIR))
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO subtitle_cache(item_id, key, mtime, status, path, checked_at, attempts) "
                      "VALUES(?,?,?,?,?,?,0)",
                      (item["id"], key, item.get("mtime"), "ready", rel, int(time.time())))
        log.info("cached subtitles item %s %s (%d bytes)", item["id"], key, dest.stat().st_size)
        return True
    except OSError:
        _sub_status(item, key, "retry")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    finally:
        _clear(p)


def _sub_status(item, key, status):
    with db.tx() as c:
        c.execute("INSERT INTO subtitle_cache(item_id, key, mtime, status, checked_at, attempts) "
                  "VALUES(?,?,?,?,?,1) ON CONFLICT(item_id, key) DO UPDATE SET "
                  "status=?, checked_at=?, attempts=subtitle_cache.attempts+1",
                  (item["id"], key, item.get("mtime"), status, int(time.time()),
                   status, int(time.time())))


# ---------------------------------------------------------------------------
# fix/transcode-stuck: one-pass, non-blocking subtitle extraction
#
# Pulling a text subtitle out of an MKV means reading the whole file. A 4.6 GB 4K remux
# on the CIFS share takes ~187 s, longer than the old 180 s per-key timeout, so some titles
# never cached. The Android TV player also asks for every text track when it starts and
# will not start the video until each request has answered; the old endpoint ran one
# full-file ffmpeg per track inside the request (44 at once for one title), so the TV sat
# on "Transcode 1080p" for minutes. Now one ffmpeg writes every track in a single read,
# in the background, and the endpoint answers at once.
# ---------------------------------------------------------------------------
SUB_PASS_TIMEOUT_S = 1800         # one read of a large remux over the share
SUB_SIDECAR_TIMEOUT_S = 20        # .srt/.ass next to the video: small
SUB_FIRST_SEG_WAIT_S = 12         # let the opening encode get its first segment out first
SUB_FAILED_COOLDOWN_S = 900       # a pass that failed recently is not re-run on every play
EMPTY_VTT = b"WEBVTT\n\n"
_inflight = {}                    # item_id -> Thread running a one-pass extraction


def text_sub_keys(item):
    """Every text subtitle key for an item (sidecars e#, embedded s#), no cap."""
    keys = []
    try:
        for i, _s in enumerate(json.loads(item.get("external_subs") or "[]")):
            keys.append("e%d" % i)
    except (TypeError, ValueError):
        pass
    try:
        for s in json.loads(item.get("subtitle_streams") or "[]"):
            if s.get("text") and s.get("index") is not None:
                keys.append("s%d" % int(s["index"]))
    except (TypeError, ValueError):
        pass
    return keys


def missing_sub_keys(item, keys=None):
    return [k for k in (keys if keys is not None else text_sub_keys(item)) if not sub_get(item, k)]


def one_pass_cmd(item, keys, outdir):
    """One ffmpeg, one read of the file, one WebVTT output per embedded stream."""
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", item["path"]]
    outs = {}
    for key in keys:
        if not (key.startswith("s") and key[1:].isdigit()):
            continue
        tmp = Path(outdir) / ("%s.vtt.tmp" % key)
        cmd += ["-map", "0:%d" % int(key[1:]), "-c:s", "webvtt", "-f", "webvtt", str(tmp)]
        outs[key] = tmp
    return (cmd if outs else None), outs


def _store_sub(item, key, tmp):
    dest = sub_path(item["id"], key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = b""
    try:
        data = Path(tmp).read_bytes()
    except OSError:
        pass
    if not data.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT"):
        data = EMPTY_VTT + data
    Path(tmp).write_bytes(data)
    Path(tmp).replace(dest)
    rel = str(dest.relative_to(config.DATA_DIR))
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO subtitle_cache(item_id, key, mtime, status, path, checked_at, attempts) "
                  "VALUES(?,?,?,?,?,?,0)",
                  (item["id"], key, item.get("mtime"), "ready", rel, int(time.time())))


def extract_item_subs(item, keys=None, timeout=SUB_PASS_TIMEOUT_S, yieldable=True):
    """Extract the given (default: all missing) text subtitle keys of one item.

    Embedded tracks share a single ffmpeg pass. yieldable=True (background idle work)
    registers the process so yield_to_playback can stop it when someone presses play;
    a pass a player is waiting on runs unregistered so playback start does not kill it.
    Returns the set of keys now cached."""
    keys = missing_sub_keys(item, keys)
    done = set()
    for key in [k for k in keys if k.startswith("e")]:
        if extract_sub(item, key, timeout=SUB_SIDECAR_TIMEOUT_S):
            done.add(key)
    emb = [k for k in keys if k.startswith("s")]
    if not emb:
        return done
    outdir = config.SUBS_DIR / str(item["id"])
    outdir.mkdir(parents=True, exist_ok=True)
    cmd, outs = one_pass_cmd(item, emb, outdir)
    if not cmd:
        return done
    p = None
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        if yieldable:
            _register("subtitles", p)
        try:
            _out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_proc(p)
            for k in emb:
                _sub_status(item, k, "retry")
            log.warning("subtitles item %s: one pass timed out after %ds (%d tracks)", item["id"], timeout, len(emb))
            return done
        if p.returncode != 0:
            for k in emb:
                _sub_status(item, k, "retry")
            log.warning("subtitles item %s: one pass failed rc=%s: %s", item["id"], p.returncode,
                        (err or b"").decode("utf-8", "replace").strip()[-300:])
            return done
        for k, tmp in outs.items():
            try:
                _store_sub(item, k, tmp)
                done.add(k)
            except OSError:
                _sub_status(item, k, "retry")
        log.info("cached subtitles item %s: %d tracks in one pass (%.0fs)", item["id"], len(done), time.time() - t0)
        return done
    except OSError:
        for k in emb:
            _sub_status(item, k, "retry")
        return done
    finally:
        if yieldable:
            _clear(p)
        for tmp in outs.values():
            try:
                Path(tmp).unlink()
            except OSError:
                pass


def subs_inflight(item_id):
    with _lock:
        t = _inflight.get(item_id)
        return bool(t is not None and t.is_alive())


def _recent_failure(item, keys):
    now = int(time.time())
    for k in keys:
        r = db.row("SELECT status, checked_at, attempts FROM subtitle_cache WHERE item_id=? AND key=?", (item["id"], k))
        if not r or r.get("status") != "retry":
            return False
        if now - int(r.get("checked_at") or 0) >= SUB_FAILED_COOLDOWN_S:
            return False
    return bool(keys)


def ensure_subs_async(item, wait_first_seg=SUB_FIRST_SEG_WAIT_S):
    """Start (once per item) a background pass that caches every missing text track.
    Returns True when a new pass was started."""
    keys = missing_sub_keys(item)
    if not keys or _recent_failure(item, keys):
        return False
    iid = item["id"]
    with _lock:
        t = _inflight.get(iid)
        if t is not None and t.is_alive():
            return False

        def run():
            try:
                deadline = time.time() + wait_first_seg
                while time.time() < deadline and busy() and not first_segment_ready(iid):
                    time.sleep(0.25)
                extract_item_subs(item, keys, timeout=SUB_PASS_TIMEOUT_S, yieldable=False)
            except Exception:
                log.exception("subtitle pass item %s", iid)
            finally:
                with _lock:
                    if _inflight.get(iid) is threading.current_thread():
                        _inflight.pop(iid, None)

        t = threading.Thread(target=run, name="subs-%s" % iid, daemon=True)
        _inflight[iid] = t
    t.start()
    return True


def wait_sub(item, key, timeout):
    """Wait up to `timeout` seconds for a cached VTT (used so a fast pass can still answer)."""
    deadline = time.time() + max(0.0, timeout)
    while True:
        hit = sub_get(item, key)
        if hit or time.time() >= deadline:
            return hit
        time.sleep(0.1)


def _keys_for(item):
    keys = []
    try:
        for i, s in enumerate(json.loads(item.get("external_subs") or "[]")):
            keys.append("e%d" % i)
    except (TypeError, ValueError):
        pass
    try:
        for s in json.loads(item.get("subtitle_streams") or "[]"):
            if s.get("text") and s.get("index") is not None:
                keys.append("s%d" % s["index"])
    except (TypeError, ValueError):
        pass
    return keys[:8]


def _do_one_subtitle():
    # newest videos first; one pass per item caches every missing text track
    now = int(time.time())
    rows = db.rows(
        "SELECT i.id, i.path, i.mtime, i.external_subs, i.subtitle_streams "
        "FROM items i "
        "WHERE i.media_type='video' AND i.probed=1 "
        "AND (i.subtitle_streams LIKE '%\"text\": true%' OR i.subtitle_streams LIKE '%\"text\":true%' "
        "     OR (i.external_subs IS NOT NULL AND i.external_subs != '' AND i.external_subs != '[]')) "
        "ORDER BY i.added_at DESC LIMIT 80")
    for item in rows:
        if subs_inflight(item["id"]):
            continue
        keys = []
        for key in text_sub_keys(item):
            cached = db.row("SELECT status, mtime, checked_at, attempts FROM subtitle_cache WHERE item_id=? AND key=?",
                            (item["id"], key))
            if cached and cached.get("status") == "ready" and cached.get("mtime") == item.get("mtime"):
                continue
            if cached and cached.get("status") == "retry":
                delay = min(21600, SUB_RETRY_S * max(1, int(cached.get("attempts") or 1)))
                if cached.get("checked_at") and now - int(cached["checked_at"]) < delay:
                    continue
            keys.append(key)
        if keys:
            return bool(extract_item_subs(item, keys, timeout=SUB_PASS_TIMEOUT_S, yieldable=True)) or True
    return False



# ---------------------------------------------------------------------------
# 2.2: backfill colour tags (throttled, never during a stream)
# ---------------------------------------------------------------------------
def _do_one_color():
    rows = db.rows(
        "SELECT id, path, pix_fmt, color_transfer, color_primaries, color_space "
        "FROM items WHERE media_type='video' AND probed=1 "
        "AND (color_transfer IS NULL OR color_primaries IS NULL) "
        "ORDER BY CASE WHEN pix_fmt LIKE '%10%' OR pix_fmt LIKE '%12%' THEN 0 ELSE 1 END, "
        "added_at DESC LIMIT 20")
    for row in rows:
        if not row.get("path") or not os.path.exists(row["path"]):
            continue
        if busy():
            return False
        try:
            code, stdout, _err = run_cmd(
                [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=color_transfer,color_primaries,color_space",
                 "-of", "csv=p=0", row["path"]],
                timeout=20, kind="color")
        except Exception:
            continue
        if code != 0:
            # store empty strings so we do not retry this file every tick
            transfer = row.get("color_transfer") or ""
            primaries = row.get("color_primaries") or ""
            space = row.get("color_space") or ""
        else:
            line = (stdout or b"").decode(errors="replace").strip().splitlines()
            parts = (line[0].split(",") + ["", "", ""])[:3] if line else ["", "", ""]
            def _clean(s):
                s = (s or "").strip()
                return s or None
            transfer = _clean(parts[0]) or row.get("color_transfer")
            primaries = _clean(parts[1]) or row.get("color_primaries")
            space = _clean(parts[2]) or row.get("color_space")
            # ffprobe prints "unknown" — keep it so we will not probe again
            if not row.get("color_transfer") and not transfer:
                transfer = "unknown"
            if not row.get("color_primaries") and not primaries:
                primaries = "unknown"
        try:
            with db.tx() as c:
                c.execute("UPDATE items SET color_transfer=?, color_primaries=?, color_space=? WHERE id=?",
                          (transfer, primaries, space, row["id"]))
        except Exception:
            log.exception("color backfill %s", row["id"])
            return False
        return True
    return False



# ---------------------------------------------------------------------------
# 2.6: classify 4K 10-bit titles (Dolby Vision, mistagged HDR10) when idle
# ---------------------------------------------------------------------------
def _do_one_hdr():
    """Light backfill: one 4K Main 10 item per tick, skipped while a stream is running.

    2.6.1 also re-checks stored hdr10-mistagged titles so leftover-SEI SDR files
    (Heart of the Beast) are flipped to sdr without waiting for the next play."""
    from . import hdr as hdrmod
    try:
        rows = db.rows(
            "SELECT id, path, pix_fmt, width, height, color_transfer, color_primaries, color_space, hdr_type "
            "FROM items WHERE media_type='video' AND probed=1 "
            "AND (hdr_type IS NULL OR hdr_type='hdr10-mistagged') "
            "AND (pix_fmt LIKE '%10%' OR pix_fmt LIKE '%12%' OR pix_fmt LIKE '%p010%') "
            "AND (COALESCE(width,0) >= 3840 OR COALESCE(height,0) >= 2160) "
            "ORDER BY CASE WHEN hdr_type='hdr10-mistagged' THEN 0 ELSE 1 END, added_at DESC LIMIT 20")
    except Exception:
        # Column missing on a pre-migrate process; migrate() adds it on startup.
        return False
    for row in rows:
        if busy():
            return False
        if not row.get("path") or not os.path.exists(row["path"]):
            try:
                with db.tx() as c:
                    c.execute("UPDATE items SET hdr_type=? WHERE id=?", (hdrmod.KIND_SDR, row["id"]))
            except Exception:
                pass
            continue
        try:
            result = hdrmod.classify_path(row["path"], frames=True)
        except Exception:
            log.exception("hdr backfill %s", row["id"])
            continue
        hdrmod.store(row["id"], result)
        log.info("hdr backfill item %s -> %s (%s)", row["id"], result.get("kind"), result.get("reason"))
        return True
    return False


# ---------------------------------------------------------------------------
# Remux cut points (chunked, NAS-friendly)
# ---------------------------------------------------------------------------
def _do_one_remux():
    # videos that are remux-eligible and have no usable, current plan
    # 2.2: prefer titles with no plan at all (most HEVC 4K plays were missing a plan), then retries.
    rows = db.rows(
        "SELECT i.id, i.path, i.mtime, i.duration, i.container, i.vcodec, i.pix_fmt, i.media_type, "
        "k.data, k.status, k.mtime AS k_mtime, k.checked_at, k.attempts "
        "FROM items i LEFT JOIN keyframes k ON k.item_id=i.id "
        "WHERE i.media_type='video' AND i.probed=1 AND i.duration > 1 "
        "AND (k.item_id IS NULL OR k.mtime IS NULL OR k.mtime != i.mtime "
        "     OR k.data IS NULL OR k.data='null' OR k.status='retry') "
        "ORDER BY CASE WHEN k.item_id IS NULL THEN 0 WHEN k.status='retry' THEN 1 ELSE 2 END, "
        "i.added_at DESC LIMIT 80")
    now = time.time()
    for row in rows:
        if not transcode.remux_eligible(row):
            continue
        fresh = row.get("k_mtime") == row.get("mtime") and row.get("data") and row["data"] != "null"
        if fresh:
            continue
        if row.get("status") == "retry" and row.get("checked_at"):
            delay = {0: 0, 1: 900, 2: 3600}.get(int(row.get("attempts") or 0), 21600)
            if now - float(row["checked_at"]) < delay:
                continue
        return bool(transcode.remux_bounds(row, probe=True))
    return False


# ---------------------------------------------------------------------------
# Opening-clip cache (first ~6s at 1080p)
# ---------------------------------------------------------------------------
def prefetch_dir(item_id, kind, start_t):
    stamp = "t%d" % int(round(float(start_t or 0)))
    return config.PREFETCH_DIR / ("%s-%s-%s" % (item_id, kind, stamp))


def apply_to_session(session, start_seg):
    """Copy cached opening segments into the session dir if they match this play.

    Only 1080p H.264 transcodes are pre-generated. Returns the number of segments copied.
    """
    if session.profile != PREFETCH_PROFILE or session.hevc or session.profile == "remux":
        return 0
    item = session.item
    start_t = start_seg * transcode.SEG
    row = _best_prefetch_row(item["id"], item.get("mtime"), start_t)
    if not row or row.get("status") != "ready" or not row.get("dir"):
        return 0
    src = config.DATA_DIR / row["dir"] if not str(row["dir"]).startswith("/") else Path(row["dir"])
    if not src.is_dir():
        return 0
    copied = 0
    for n in range(start_seg, start_seg + PREFETCH_SEGS):
        name = "seg%d.ts" % n
        sp = src / name
        if sp.is_file() and sp.stat().st_size > 1000:
            dest = session.dir / name
            if not dest.exists():
                shutil.copy2(sp, dest)
            copied += 1
    if copied:
        with db.tx() as c:
            c.execute("UPDATE prefetch_cache SET last_access=? WHERE item_id=? AND kind=? AND start_t=?",
                      (int(time.time()), row["item_id"], row["kind"], row["start_t"]))
        log.info("prefetch hit item %s start_seg %d (%d segs)", item["id"], start_seg, copied)
    return copied


def _best_prefetch_row(item_id, mtime, start_t):
    rows = db.rows("SELECT * FROM prefetch_cache WHERE item_id=? AND status='ready' AND mtime=?",
                   (item_id, mtime))
    hit = None
    for r in rows:
        if abs((r.get("start_t") or 0) - (start_t or 0)) < transcode.SEG / 2:
            hit = r
            break
    return hit


def _do_one_prefetch():
    evict_lru()
    if cache_gb() <= 0:
        return False
    targets = _prefetch_targets()
    for item, kind, start_t in targets:
        if busy():
            return False
        if _best_prefetch_row(item["id"], item.get("mtime"), start_t):
            continue
        return _build_prefetch(item, kind, start_t)
    return False


def _prefetch_targets():
    """Recently added (from the start) and Continue Watching resume points."""
    out = []
    seen = set()
    # Continue Watching first: these are the next play the user is likely to open
    for r in db.rows(
            "SELECT i.id, i.path, i.mtime, i.duration, i.width, i.height, i.vcodec, i.pix_fmt, i.rotation, "
            "i.color_transfer, i.media_type, i.audio_streams, i.container, p.position "
            "FROM progress p JOIN items i ON i.id=p.item_id "
            "WHERE i.media_type='video' AND i.probed=1 AND p.watched=0 AND p.position > 30 "
            "ORDER BY p.updated_at DESC LIMIT 20"):
        start_seg = int((r["position"] or 0) // transcode.SEG)
        start_t = start_seg * transcode.SEG
        key = (r["id"], "resume", start_t)
        if key not in seen:
            seen.add(key)
            out.append((r, "resume", start_t))
    for r in db.rows(
            "SELECT i.id, i.path, i.mtime, i.duration, i.width, i.height, i.vcodec, i.pix_fmt, i.rotation, "
            "i.color_transfer, i.media_type, i.audio_streams, i.container "
            "FROM items i WHERE i.media_type='video' AND i.probed=1 "
            "ORDER BY i.added_at DESC LIMIT 25"):
        key = (r["id"], "start", 0.0)
        if key not in seen:
            seen.add(key)
            out.append((r, "start", 0.0))
    return out


def _build_prefetch(item, kind, start_t):
    if not os.path.exists(item.get("path") or ""):
        return False
    dest = prefetch_dir(item["id"], kind, start_t)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    start_seg = int(round(start_t / transcode.SEG)) if start_t else 0
    # A throwaway session writes into dest using the same 1080p command as a live play.
    sid = "prefetch-%s-%s" % (item["id"], kind)
    try:
        s = transcode.Session(sid, item, PREFETCH_PROFILE, 0)
    except ValueError:
        shutil.rmtree(dest, ignore_errors=True)
        return False
    # Point the session at our cache dir (Session already mkdir'd under TRANSCODE_DIR)
    live_dir = s.dir
    s.dir = dest
    s.start_seg = start_seg
    cmd = s._cmd(start_seg)
    # restore / clean the placeholder transcode dir
    try:
        shutil.rmtree(live_dir, ignore_errors=True)
    except OSError:
        pass
    log.info("prefetch build item %s %s t=%.1f", item["id"], kind, start_t)
    def _low():
        try:
            os.nice(10)
        except OSError:
            pass
        os.setsid()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_low)
        _register("prefetch", proc)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        return False
    last = start_seg + PREFETCH_SEGS - 1
    t0 = time.time()
    ok = False
    try:
        while time.time() - t0 < 45:
            if busy():
                # a real viewer arrived; abandon immediately so we do not contend
                break
            if (dest / ("seg%d.ts" % last)).is_file() and (dest / ("seg%d.ts" % last)).stat().st_size > 1000:
                ok = True
                break
            time.sleep(0.15)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        _clear(proc)
    size = 0
    for f in dest.glob("seg*.ts"):
        try:
            size += f.stat().st_size
        except OSError:
            pass
    if not ok or size < 1000:
        shutil.rmtree(dest, ignore_errors=True)
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO prefetch_cache(item_id, kind, start_t, mtime, profile, dir, size, "
                      "last_access, status, checked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (item["id"], kind, start_t, item.get("mtime"), PREFETCH_PROFILE, None, 0,
                       int(time.time()), "retry", int(time.time())))
        return False
    rel = str(dest.relative_to(config.DATA_DIR))
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO prefetch_cache(item_id, kind, start_t, mtime, profile, dir, size, "
                  "last_access, status, checked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (item["id"], kind, start_t, item.get("mtime"), PREFETCH_PROFILE, rel, size,
                   int(time.time()), "ready", int(time.time())))
    log.info("prefetch ready item %s %s (%d bytes)", item["id"], kind, size)
    return True


def evict_lru():
    cap = int(cache_gb() * 1024 * 1024 * 1024)
    rows = db.rows("SELECT item_id, kind, start_t, dir, size, last_access FROM prefetch_cache WHERE status='ready' "
                   "ORDER BY last_access ASC")
    total = sum(int(r.get("size") or 0) for r in rows)
    # also count stray files
    if total <= cap:
        return
    for r in rows:
        if total <= cap:
            break
        if r.get("dir"):
            p = config.DATA_DIR / r["dir"] if not str(r["dir"]).startswith("/") else Path(r["dir"])
            shutil.rmtree(p, ignore_errors=True)
        with db.tx() as c:
            c.execute("DELETE FROM prefetch_cache WHERE item_id=? AND kind=? AND start_t=?",
                      (r["item_id"], r["kind"], r["start_t"]))
        total -= int(r.get("size") or 0)
        log.info("prefetch evict item %s %s (%s bytes)", r["item_id"], r["kind"], r.get("size"))


def cache_stats():
    rows = db.rows("SELECT status, COUNT(*) AS n, COALESCE(SUM(size),0) AS bytes FROM prefetch_cache GROUP BY status")
    ready = next((r for r in rows if r["status"] == "ready"), {"n": 0, "bytes": 0})
    return {"gb": cache_gb(), "clips": int(ready.get("n") or 0),
            "bytes": int(ready.get("bytes") or 0), "rows": rows}
