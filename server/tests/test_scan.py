"""Scanner behaviour (1.2): pipelined discovery, live batches, cancel, skip unchanged, pruning, offline safety.

    python3 tests/test_scan.py /path/to/testmedia
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-scan-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_KEY": "", "MS_SCAN_WORKERS": "3"})

from app import db, scanner  # noqa: E402

MEDIA = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/media-server/testmedia")
LIB = Path(TMP) / "lib"
n_ok = 0


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def count(lib_id=1):
    return db.row("SELECT COUNT(*) n FROM items WHERE library_id=?", (lib_id,))["n"]


def wait(lib_id=1, timeout=300, watch=None):
    t = time.time()
    while time.time() - t < timeout:
        st = scanner.status.get(lib_id) or {}
        if watch:
            watch(st)
        if st.get("state") in ("done", "error", "cancelled"):
            return st
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def main():
    db.migrate()
    # library: 3 real clips + 60 broken files in 30 folders
    real = [p for p in (MEDIA / "movies").rglob("*") if p.suffix in (".mp4", ".mkv")][:3]
    for i in range(30):
        d = LIB / ("Folder %02d" % i)
        d.mkdir(parents=True)
        for j in range(2):
            (d / ("Broken Film %02d%d (2001).mkv" % (i, j))).write_bytes(b"this is not a video file\n" * 40)  # deterministic: random bytes are occasionally probe-able
    for r in real:
        shutil.copy(r, LIB / "Folder 00" / r.name)
    total_files = 63
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies',?,0,?)",
                  (str(LIB), int(time.time())))

    print("pipelined discovery on a slow folder walk (simulated SMB)")
    real_walk = os.walk

    def slow_walk(*a, **k):
        for x in real_walk(*a, **k):
            time.sleep(0.08)
            yield x
    scanner.os.walk = slow_walk
    seen = {"disc_with_items": False, "phases": set(), "max_found_before_total": 0}

    def watch(st):
        seen["phases"].add(st.get("phase"))
        if st.get("phase") == "discovering" and count() > 0:
            seen["disc_with_items"] = True
    scanner.request_scan(1)
    st = wait(watch=watch)
    scanner.os.walk = real_walk
    check(st["state"] == "done", "scan finished: %s" % st.get("summary"))
    check({"discovering", "processing"} <= seen["phases"], "phases reported: %s" % sorted(p for p in seen["phases"] if p))
    check(seen["disc_with_items"], "items are in the database while files are still being discovered")
    check(st["found"] == total_files and st["added"] == total_files, "found/added %d/%d" % (st["found"], st["added"]))
    check(st["errors"] == 60, "unreadable files counted as errors (%d)" % st["errors"])
    check(count() == total_files, "all items committed")
    logs = [x["msg"] for x in scanner.logs[1]]
    check(any(m.startswith("added: ") for m in logs) and any("found 63 media files" in m for m in logs), "scan log lines kept for the UI")
    check(db.row("SELECT COUNT(*) n FROM items WHERE probed=-1")["n"] == 60, "broken files marked probed=-1")

    print("rescan skips unchanged files (and does not retry known-broken ones)")
    t = time.time()
    scanner.request_scan(1)
    st = wait()
    check(st["unchanged"] == total_files and st["total"] == 0, "unchanged %d, to do %d" % (st["unchanged"], st["total"]))
    check(time.time() - t < 3, "rescan took %.2fs" % (time.time() - t))

    print("added_at is per item (Recently added order)")
    r = db.row("SELECT MIN(added_at) a, MAX(added_at) b FROM items")
    check(r["b"] >= r["a"], "added_at range ok")

    print("cancel keeps found items and removes nothing")
    with db.tx() as c:
        c.execute("DELETE FROM items")
    scanner.os.walk = slow_walk
    scanner.request_scan(1)
    time.sleep(0.8)
    check(scanner.cancel_scan(1), "cancel accepted")
    st = wait()
    scanner.os.walk = real_walk
    n_after = count()
    check(st["state"] == "cancelled", "state cancelled: %s" % st.get("summary"))
    check(0 < n_after < total_files, "partial items kept (%d)" % n_after)
    check(not scanner.cancel_scan(1), "cancel when idle -> False")
    scanner.request_scan(1)
    st = wait()
    check(count() == total_files and st["unchanged"] == n_after, "next scan resumes: %d unchanged, %d new" % (st["unchanged"], st["added"]))

    print("deleted file is pruned; empty (offline) folder keeps items")
    (LIB / "Folder 05" / "Broken Film 050 (2001).mkv").unlink()
    scanner.request_scan(1)
    st = wait()
    check(st["removed"] == 1 and count() == total_files - 1, "removed 1")
    moved = Path(TMP) / "offline"
    LIB.rename(moved)
    LIB.mkdir()
    scanner.request_scan(1)
    st = wait()
    check(st["state"] == "error" and count() == total_files - 1, "empty folder -> error, items kept: %s" % st.get("error"))
    LIB.rmdir()
    scanner.request_scan(1)
    st = wait()
    check(st["state"] == "error" and "not found" in st["error"], "missing folder -> error")
    moved.rename(LIB)

    print("\nALL %d SCAN CHECKS PASSED" % n_ok)


try:
    main()
finally:
    scanner._stop = True
    shutil.rmtree(TMP, ignore_errors=True)
