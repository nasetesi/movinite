"""1.6: share status dots -- cached, timeout-guarded checks of network-share libraries.

    python3 tests/test_sharehealth16.py
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-sh16-")
os.environ["MS_DATA_DIR"] = TMP + "/data"
from app import db, server, sharehealth, shares  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    db.migrate()
    d = Path(TMP) / "share1"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x")
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO shares(id,name,kind,remote,mount_point,created_at) VALUES(1,'nas','smb','//nas/Media','',?)", (now,))
        c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at) VALUES(1,'NAS Movies','movies',?,1,0,?)", (str(d), now))
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(2,'Local','tv',?,0,?)", (str(d), now))
    mounted = {"v": True}
    shares.is_mounted = lambda sid: mounted["v"]
    lib = dict(db.row("SELECT * FROM libraries WHERE id=1"))
    check(sharehealth.get(lib)["state"] == "checking", "before the first check: checking (grey)")
    check(sharehealth.get(dict(db.row("SELECT * FROM libraries WHERE id=2"))) is None, "local-folder library: no dot")
    st = sharehealth.check(lib)
    check(st["state"] == "online", "mounted + listable: online (%s)" % st)
    out = {l["id"]: l for l in server.list_libraries(None)}
    check(out[1]["health"]["state"] == "online" and out[1]["health"]["age_s"] is not None and out[1]["online"], "GET /api/libraries carries health + age")
    check(out[2]["health"] is None, "local library has health null")
    mounted["v"] = False
    st = sharehealth.check(lib)
    check(st["state"] == "offline" and "not mounted" in st["reason"], "unmounted: offline, reason 'share not mounted'")
    check({l["id"]: l for l in server.list_libraries(None)}[1]["online"] is False, "API marks it not online")
    mounted["v"] = True
    lib2 = dict(lib, path=str(d / "gone"))
    st = sharehealth.check(lib2)
    check(st["state"] == "offline" and "not found" in st["reason"], "folder missing: offline (%s)" % st["reason"])
    # a hung mount: listing never returns -> amber within the timeout, the server is not blocked, no second probe piles up
    gate = threading.Event()
    real = os.scandir
    calls = {"n": 0}

    def hung(p):
        calls["n"] += 1
        gate.wait(30)
        return real(p)
    sharehealth.os.scandir = hung
    sharehealth.LIST_TIMEOUT_S = 0.5
    t0 = time.time()
    st = sharehealth.check(lib)
    check(st["state"] == "stuck" and time.time() - t0 < 1.5, "hung mount: 'not responding' after the timeout (%.2fs)" % (time.time() - t0))
    st = sharehealth.check(lib)
    check(st["state"] == "stuck" and calls["n"] == 1, "while still hung, no second listing thread is started")
    t0 = time.time()
    server.list_libraries(None)
    check(time.time() - t0 < 0.5, "GET /api/libraries does not touch the hung mount")
    gate.set()
    time.sleep(0.2)
    sharehealth.os.scandir = real
    st = sharehealth.check(lib)
    check(st["state"] == "online", "back to online once the share answers again")
    # on-demand endpoint (rate-limited)
    r = server.libraries_health(None)
    check(r.get("1", {}).get("state") == "online" and "2" not in r, "POST /api/libraries/health returns share libraries only")
    check(sharehealth.check_all() is False, "on-demand checks are rate-limited")
    src = (HERE.parent / "app" / "sharehealth.py").read_text()
    check("remount" not in src.split('"""', 2)[2], "the health check never remounts")
    js = (HERE.parent / "app" / "static" / "app.js").read_text()
    check("function shareDot" in js and "Share online" in js and "Share offline: " in js and "${shareDot(l)}" in js, "side menu + phone Libraries tab show the dot with a tooltip")
    print("FAILS: %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
