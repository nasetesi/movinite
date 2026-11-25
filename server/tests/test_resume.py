"""1.2.1: TMDB matching resumes after a restart, 'Posters first' ordering, index version stamping.

    python3 tests/test_resume.py /path/to/testmedia
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9558
TMP = tempfile.mkdtemp(prefix="ms-resume-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "20"})

import mock_tmdb  # noqa: E402
from app import db, scanner, server, settings, tmdb  # noqa: E402
from app.version import __version__  # noqa: E402

MEDIA = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/media-server/testmedia")
n_ok = 0


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def wait_meta(lib_id, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        st = tmdb.status.get(lib_id) or {}
        if st.get("state") in ("done", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError("metadata run timed out: %s" % tmdb.status.get(lib_id))


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies',?,0,?)",
                  (str(MEDIA / "movies"), int(time.time())))
    U = {"id": 1, "is_admin": 1}

    print("key saved / restart while idle -> nothing was matching")
    settings.put("tmdb_enabled", "0")
    scanner.scan_library(1)
    settings.put("tmdb_enabled", "1")
    tmdb.status.clear()
    pend = tmdb.pending_count(1)
    check(pend >= 4, "movies waiting for a lookup: %d" % pend)
    items = server.library_items(1, sort="poster", u=U)["items"]
    local = db.row("SELECT COUNT(*) n FROM items WHERE library_id=1 AND poster<>thumb")["n"]
    check(sum(i["has_art"] for i in items) == local, "only local poster.jpg counts as artwork before TMDB (%d)" % local)
    lib = server._lib_out(db.row("SELECT * FROM libraries WHERE id=1"))
    check(lib["meta_counts"]["pending"] == pend, "pending count exposed to the UI")

    print("resume_pending() picks it up (startup / periodic check)")
    q = tmdb.resume_pending()
    check(q == [1], "library 1 queued: %s" % q)
    st = wait_meta(1)
    check(st["state"] == "done" and st["matched"] >= 3, "matched %s of %s" % (st["matched"], st["total"]))
    check(st.get("rate_per_min") is not None, "rate / ETA reported (%s/min)" % st.get("rate_per_min"))
    check(tmdb.pending_count(1) == 0, "nothing pending afterwards (no-match retries wait)")
    tmdb._last_resume.clear()
    check(tmdb.resume_pending() == [], "no pointless re-queue when nothing is pending")

    print("posters first")
    items = server.library_items(1, sort="poster", u=U)["items"]
    arts = [i["has_art"] for i in items]
    check(any(arts) and not all(arts), "mix of artwork / no artwork: %s" % arts)
    check(arts == sorted(arts, reverse=True), "artwork titles come first")
    withart = [i["title"] for i in items if i["has_art"]]
    check(all(i["poster"] for i in items if i["has_art"]), "has_art items carry a poster")
    print("   ", withart)
    t_items = server.library_items(1, sort="title", u=U)["items"]
    check(len(t_items) == len(items), "title sort still lists everything")
    home = server.home(u=U)["libraries"][0]["items"]
    ha = [i["has_art"] for i in home]
    check(ha == sorted(ha, reverse=True) and any(ha), "Home 'Recently added' puts artwork first")

    print("interrupted run (update restart mid-match) resumes")
    with db.tx() as c:
        c.execute("UPDATE items SET meta_status=NULL, tmdb_id=NULL WHERE library_id=1 AND title LIKE 'Remux%'")
    tmdb.status[1] = {"state": "done", "finished_at": time.time()}
    tmdb._last_resume.clear()
    check(tmdb.pending_count(1) == 1, "one movie lost its match")
    check(tmdb.resume_pending() == [1], "queued again")
    wait_meta(1)
    r = db.row("SELECT meta_status, tmdb_id FROM items WHERE title LIKE 'Remux%'")
    check(r["meta_status"] == "matched" and r["tmdb_id"] == 1003, "re-matched: %s" % dict(r))

    print("TMDB off / failing -> no resume loop hammering")
    settings.put("tmdb_enabled", "0")
    with db.tx() as c:
        c.execute("UPDATE items SET meta_status=NULL WHERE library_id=1")
    tmdb._last_resume.clear()
    check(tmdb.resume_pending() == [], "disabled -> nothing queued")
    settings.put("tmdb_enabled", "1")
    tmdb.status[1] = {"state": "error", "error": "network", "finished_at": time.time()}
    check(tmdb.resume_pending() == [], "recent error -> backs off")

    print("index.html")
    html = server._index_response().body.decode()
    check(("app.js?v=%s\"" % __version__) in html and ("style.css?v=%s\"" % __version__) in html,
          "asset URLs stamped with v%s" % __version__)
    print("\nALL %d RESUME CHECKS PASSED" % n_ok)


if __name__ == "__main__":
    main()
