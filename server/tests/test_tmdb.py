"""TMDB integration against the mock API (tests/mock_tmdb.py). No internet or real key needed.

    python3 tests/test_tmdb.py /path/to/testmedia
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9557
TMP = tempfile.mkdtemp(prefix="ms-tmdb-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "10"})

import mock_tmdb  # noqa: E402
from app import config, db, scanner, settings, tmdb  # noqa: E402

MEDIA = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MOVINITE_TESTMEDIA", str(Path(__file__).resolve().parent / "testmedia")))
ok_count = 0


def check(cond, msg):
    global ok_count
    if not cond:
        raise AssertionError(msg)
    ok_count += 1
    print("  ok -", msg)


def wait_meta(lib_id, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        st = tmdb.status.get(lib_id) or {}
        if st.get("state") in ("done", "error"):
            return st
        time.sleep(0.2)
    raise AssertionError("metadata run timed out: %s" % tmdb.status.get(lib_id))


def main():
    srv = mock_tmdb.serve(PORT)
    db.migrate()
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies',?,0,?)",
                  (str(MEDIA / "movies"), now))
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(2,'TV','tv',?,0,?)",
                  (str(MEDIA / "tv"), now))
    print("scan + automatic TMDB matching")
    scanner.scan_library(1)
    scanner.scan_library(2)
    st1, st2 = wait_meta(1), wait_meta(2)
    print("   ", st1, "\n   ", st2)
    items = {r["title"]: r for r in db.rows("SELECT * FROM items WHERE library_id=1")}
    check(items["Big Test Movie"]["tmdb_id"] == 1001, "Big Test Movie (2019) -> TMDB 1001")
    check(items["Another Film"]["tmdb_id"] == 1002, "Another Film (2021) matched the 2021 film, not the 1985 decoy")
    check(items["Remux Test"]["tmdb_id"] == 1003, "Remux Test (2022) -> 1003")
    check(items["Old Clip"]["meta_status"] == "nomatch" and items["Old Clip"]["tmdb_id"] is None, "Old Clip: no match, keeps file name")
    m = tmdb.cached("movie", 1001)
    check(m and m["overview"] and json.loads(m["genres"]) == ["Drama", "Science Fiction"] and m["rating"] == 7.8, "details cached (overview, genres, rating)")
    check(m["poster"] and (config.THUMB_DIR / m["poster"]).is_file(), "poster downloaded into data/thumbs")
    check(m["backdrop"] and (config.THUMB_DIR / m["backdrop"]).is_file(), "backdrop downloaded")
    sm = db.row("SELECT * FROM show_matches WHERE library_id=2 AND show='Test Show'")
    check(sm and sm["tmdb_id"] == 2001 and sm["status"] == "matched", "Test Show -> TMDB 2001")
    eps = {(e["season"], e["episode"]): e for e in db.rows("SELECT * FROM tmdb_episodes WHERE tv_id=2001")}
    check(eps[(1, 1)]["name"] == "The Real Pilot" and eps[(2, 1)]["name"] == "Homecoming", "episode titles cached")
    check(eps[(1, 1)]["still"] and not eps[(1, 3)]["still"], "stills downloaded only for episodes on disk")

    print("enrichment")
    rows = db.rows("SELECT * FROM items WHERE library_id IN (1,2)")
    tmdb.enrich(rows)
    by = {(r["kind"], r.get("file_title") or r["title"], r["season"], r["episode"]): r for r in rows}
    big = by[("movie", "Big Test Movie", None, None)]
    check(big["title"] == "The Big Test Movie" and big["overview"] and big["backdrop"], "movie title/overview/backdrop overlaid")
    check(big["poster"] != m["poster"], "local poster.jpg still wins over the TMDB poster")
    other = by[("movie", "Another Film", None, None)]
    check(other["poster"] == tmdb.cached("movie", 1002)["poster"], "TMDB poster replaces a frame grab")
    ep = next(r for r in rows if r["kind"] == "episode" and r["season"] == 1 and r["episode"] == 1)
    check(ep["title"] == "The Real Pilot" and ep["thumb"] == eps[(1, 1)]["still"], "episode title + still overlaid")
    oc = by[("movie", "Old Clip", None, None)]
    check(oc["title"] == "Old Clip" and "overview" not in oc, "unmatched item unchanged")

    print("rate limiting")
    times = sorted(mock_tmdb.stats["times"])
    worst = max(sum(1 for t in times if t0 <= t < t0 + 1.0) for t0 in times)
    check(worst <= 11, "never more than ~10 API requests per second (worst 1s window: %d)" % worst)

    print("429 handling")
    os.environ["MOCK_TMDB_429_EVERY"] = "3"
    tmdb.queue_library(1, force=True)
    st = wait_meta(1)
    os.environ["MOCK_TMDB_429_EVERY"] = "0"
    check(mock_tmdb.stats["429"] > 0 and tmdb.stats["rate_limited"] > 0, "server answered 429 %d times" % mock_tmdb.stats["429"])
    check(st["state"] == "done" and st.get("errors", 0) == 0 and st["matched"] == 3, "run still completed after Retry-After waits: %s" % st)

    print("manual fix match / unmatch")
    oid = items["Another Film"]["id"]
    tmdb.fetch_details("movie", 1099, force=True)
    tmdb.apply_movie_match([oid], 1099, "manual")
    tmdb.queue_library(1)
    wait_meta(1)
    check(db.row("SELECT tmdb_id FROM items WHERE id=?", (oid,))["tmdb_id"] == 1099, "manual match survives automatic runs")
    tmdb.apply_movie_match([oid], None, "unmatched")
    tmdb.queue_library(1, force=True)
    wait_meta(1)
    r = db.row("SELECT tmdb_id, meta_status FROM items WHERE id=?", (oid,))
    check(r["tmdb_id"] is None and r["meta_status"] == "unmatched", "'use file name' (unmatch) survives even a forced refresh")

    print("v4 read token")
    check(tmdb.test_key("eyJmock.token.sig")[0], "v4 token sent as Bearer works")
    check(not tmdb.test_key("BADKEY123456789012")[0], "bad key rejected")

    print("bad key / TMDB unreachable -> graceful")
    settings.put("tmdb_key", "BADKEY123456789012")   # gitleaks:allow -- fake test key
    tmdb.queue_library(2, force=True)
    st = wait_meta(2)
    check(st["state"] == "error" and "rejected" in st["error"], "bad key: run stops with a clear error")
    check(db.row("SELECT tmdb_id FROM show_matches WHERE show='Test Show'")["tmdb_id"] == 2001, "existing matches untouched")
    settings.put("tmdb_key", "")
    srv.shutdown(); srv.server_close()
    t0 = time.time()
    tmdb.queue_library(1, force=True)
    st = wait_meta(1, 120)
    check(st["state"] == "error" and "reach" in st["error"] and time.time() - t0 < 20,
          "TMDB down: run stops quickly (%.1fs) with 'Cannot reach TMDB'" % (time.time() - t0))
    check(db.row("SELECT tmdb_id FROM items WHERE title='Big Test Movie'")["tmdb_id"] == 1001, "cached metadata still used")
    settings.put("tmdb_enabled", "0")
    check(not tmdb.queue_library(1), "no key / disabled: nothing is queued (file-name metadata only)")
    print("\nALL %d CHECKS PASSED" % ok_count)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
