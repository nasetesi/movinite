"""2.2: seek-bar trickplay sprites (background, GPU when possible, throttled, disk-capped).

A viewer never waits for this job. The player shows timestamps until a sheet is ready,
then uses the sprites on hover / scrub.
"""
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import config, db, hwaccel

log = logging.getLogger("media-server.trickplay")

INTERVAL = 10.0
THUMB_W = 160
COLS = 10
ROWS = 10
DEFAULT_CACHE_GB = 3.0
PER_SHEET = COLS * ROWS


def cache_gb():
    try:
        from . import settings
        raw = settings.get("trickplay_cache_gb")
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
        raise ValueError("Trickplay cache must be between 0 and 100 GB")
    settings.put("trickplay_cache_gb", str(n))
    evict_lru()


def cache_stats():
    rows = db.rows("SELECT status, COUNT(*) AS n, COALESCE(SUM(size),0) AS bytes FROM trickplay_cache GROUP BY status")
    ready = next((r for r in rows if r["status"] == "ready"), {"n": 0, "bytes": 0})
    return {"gb": cache_gb(), "titles": int(ready.get("n") or 0),
            "bytes": int(ready.get("bytes") or 0), "rows": rows}


def item_dir(item_id):
    return config.TRICKPLAY_DIR / str(int(item_id))


def _sheet_size(path):
    # JPEG SOF0/SOF2: parse width/height without extra deps
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None, None
    i = 0
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = (data[i + 5] << 8) + data[i + 6]
            w = (data[i + 7] << 8) + data[i + 8]
            return w, h
        if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
            i += 2
            continue
        seglen = (data[i + 2] << 8) + data[i + 3]
        i += 2 + seglen
    return None, None


def public_info(item, touch=True):
    """JSON the player needs, or None if nothing is ready."""
    if not item or not item.get("id"):
        return None
    row = db.row("SELECT * FROM trickplay_cache WHERE item_id=?", (item["id"],))
    if not row or row.get("status") not in ("ready", "partial"):
        return None
    if row.get("mtime") != item.get("mtime"):
        return None
    dest = item_dir(item["id"])
    sheets = sorted(dest.glob("sheet*.jpg"))
    if not sheets:
        return None
    if touch:
        try:
            with db.tx() as c:
                c.execute("UPDATE trickplay_cache SET last_access=? WHERE item_id=?",
                          (int(time.time()), item["id"]))
        except Exception:
            pass
    w = int(row["width"] or THUMB_W)
    h = int(row["height"] or int(round(THUMB_W * 9 / 16)))
    cols = int(row["columns"] or COLS)
    rows = int(row["rows"] or ROWS)
    return {
        "interval": float(row["interval_s"] or INTERVAL),
        "width": w, "height": h, "columns": cols, "rows": rows,
        "count": int(row["count"] or 0),
        "sheets": ["/api/items/%s/trickplay/sheet%d.jpg" % (item["id"], i) for i in range(len(sheets))],
        "status": row["status"],
    }


def sheet_path(item_id, n):
    p = item_dir(item_id) / ("sheet%d.jpg" % int(n))
    return p if p.is_file() else None


def evict_lru():
    cap = int(cache_gb() * 1024 * 1024 * 1024)
    rows = db.rows("SELECT item_id, dir, size, last_access FROM trickplay_cache WHERE status IN ('ready','partial') "
                   "ORDER BY last_access ASC")
    total = sum(int(r.get("size") or 0) for r in rows)
    if total <= cap:
        return
    for r in rows:
        if total <= cap:
            break
        dest = item_dir(r["item_id"])
        shutil.rmtree(dest, ignore_errors=True)
        with db.tx() as c:
            c.execute("DELETE FROM trickplay_cache WHERE item_id=?", (r["item_id"],))
        total -= int(r.get("size") or 0)
        log.info("trickplay evict item %s (%s bytes)", r["item_id"], r.get("size"))


def _do_one():
    """Build sprites for one video while idle. Returns True if work was attempted."""
    if cache_gb() <= 0:
        return False
    from . import preload, transcode
    if preload.busy():
        return False
    rows = db.rows(
        "SELECT i.id, i.path, i.mtime, i.duration, i.width, i.height, i.media_type, i.vcodec, "
        "t.status, t.mtime AS t_mtime, t.checked_at, t.attempts "
        "FROM items i LEFT JOIN trickplay_cache t ON t.item_id=i.id "
        "WHERE i.media_type='video' AND i.probed=1 AND i.duration > 30 "
        "ORDER BY CASE WHEN t.item_id IS NULL THEN 0 WHEN t.status='retry' THEN 1 ELSE 2 END, "
        "i.added_at DESC LIMIT 40")
    now = time.time()
    for row in rows:
        if not row.get("path") or not os.path.exists(row["path"]):
            continue
        fresh = row.get("t_mtime") == row.get("mtime") and row.get("status") in ("ready",)
        if fresh:
            continue
        if row.get("status") == "retry" and row.get("checked_at"):
            delay = {0: 0, 1: 900, 2: 3600}.get(int(row.get("attempts") or 0), 21600)
            if now - float(row["checked_at"]) < delay:
                continue
        return _build(row)
    return False


def _build(item):
    from . import preload
    dest = item_dir(item["id"])
    work = dest / "work"
    shutil.rmtree(dest, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    dur = float(item.get("duration") or 0)
    n = max(1, int(dur // INTERVAL) + (1 if dur % INTERVAL > 1 else 0))
    # ffmpeg: one JPEG every INTERVAL seconds, scaled to THUMB_W.
    frames = work / "f%04d.jpg"
    vf = "fps=1/%g,scale=%d:-2" % (INTERVAL, THUMB_W)
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", "0", "-i", item["path"], "-an", "-sn", "-dn",
           "-vf", vf, "-q:v", "6", "-frames:v", str(min(n, 4000)), str(frames)]
    method, device = hwaccel.active()
    if method == "vaapi" and device:
        # Decode and scale on the GPU, download for JPEG. fps/scale_vaapi stay on the card.
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-threads", "1", "-hwaccel", "vaapi", "-hwaccel_device", device,
               "-hwaccel_output_format", "vaapi", "-extra_hw_frames", "16",
               "-ss", "0", "-i", item["path"], "-an", "-sn", "-dn",
               "-vf", "fps=1/%g,scale_vaapi=w=%d:h=-2:format=nv12,hwdownload,format=nv12" % (INTERVAL, THUMB_W),
               "-q:v", "6", "-frames:v", str(min(n, 4000)), str(frames)]
    log.info("trickplay build item %s (%ss)", item["id"], int(dur))

    def _low():
        try:
            os.nice(10)
        except OSError:
            pass
        os.setsid()

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_low)
        preload._register("trickplay", proc)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        _mark(item, "retry", 0)
        return False
    ok = False
    try:
        t0 = time.time()
        while time.time() - t0 < max(90, min(600, dur / 2)):
            if preload.busy():
                break
            if proc.poll() is not None:
                ok = proc.returncode == 0
                break
            time.sleep(0.2)
        else:
            ok = proc.poll() == 0
    finally:
        if proc.poll() is None:
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
        preload._clear(proc)

    jpgs = sorted(work.glob("f*.jpg"))
    if len(jpgs) < 2:
        shutil.rmtree(dest, ignore_errors=True)
        _mark(item, "retry", 0)
        return False

    # Tile into 10x10 sheets with ffmpeg (no Pillow dependency).
    thumb_w, thumb_h = THUMB_W, int(round(THUMB_W * 9 / 16))
    w0, h0 = _sheet_size(jpgs[0])
    if w0 and h0:
        thumb_w, thumb_h = w0, h0
    sheets = 0
    for i in range(0, len(jpgs), PER_SHEET):
        if preload.busy():
            break
        batch = jpgs[i:i + PER_SHEET]
        seq = work / ("s%d" % sheets)
        if seq.exists():
            shutil.rmtree(seq, ignore_errors=True)
        seq.mkdir()
        for j, im in enumerate(batch):
            dest_j = seq / ("%03d.jpg" % (j + 1))
            try:
                os.link(im, dest_j)
            except OSError:
                shutil.copy2(im, dest_j)
        # pad
        last = batch[-1]
        for j in range(len(batch), PER_SHEET):
            dest_j = seq / ("%03d.jpg" % (j + 1))
            try:
                os.link(last, dest_j)
            except OSError:
                shutil.copy2(last, dest_j)
        out = dest / ("sheet%d.jpg" % sheets)
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-framerate", "1", "-i", str(seq / "%03d.jpg"),
               "-vf", "tile=%dx%d" % (COLS, ROWS), "-frames:v", "1", "-q:v", "5", str(out)]
        rc, _, err = preload.run_cmd(cmd, timeout=60, kind="trickplay")
        if rc != 0 or not out.is_file() or out.stat().st_size < 100:
            log.warning("trickplay tile failed item %s sheet %s rc=%s", item["id"], sheets, rc)
            break
        sheets += 1

    shutil.rmtree(work, ignore_errors=True)
    ready_sheets = sorted(dest.glob("sheet*.jpg"))
    size = sum(f.stat().st_size for f in ready_sheets)
    if not ready_sheets or size < 1000:
        shutil.rmtree(dest, ignore_errors=True)
        _mark(item, "retry", 0)
        return False
    status = "ready" if sheets * PER_SHEET >= min(len(jpgs), n) or len(ready_sheets) * PER_SHEET >= len(jpgs) else "partial"
    rel = str(dest.relative_to(config.DATA_DIR))
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO trickplay_cache(item_id, mtime, interval_s, width, height, columns, rows, "
            "count, sheets, dir, size, status, last_access, checked_at, attempts) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item.get("mtime"), INTERVAL, thumb_w, thumb_h, COLS, ROWS,
             len(jpgs), len(ready_sheets), rel, size, status,
             int(time.time()), int(time.time()), 0))
    evict_lru()
    log.info("trickplay %s item %s (%d thumbs, %d sheets, %d bytes)", status, item["id"], len(jpgs), len(ready_sheets), size)
    return True


def _mark(item, status, size):
    attempts = 0
    row = db.row("SELECT attempts FROM trickplay_cache WHERE item_id=?", (item["id"],))
    if row:
        attempts = int(row.get("attempts") or 0) + 1
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO trickplay_cache(item_id, mtime, interval_s, width, height, columns, rows, "
            "count, sheets, dir, size, status, last_access, checked_at, attempts) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item.get("mtime"), INTERVAL, THUMB_W, 0, COLS, ROWS,
             0, 0, None, size, status, int(time.time()), int(time.time()), attempts))
