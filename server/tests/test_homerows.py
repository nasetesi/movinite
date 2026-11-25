"""1.4.1: Home rows -- Recommended, Recently released, Recently added, Top movies, Continue watching, pins.

    python3 tests/test_homerows.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9562
TMP = tempfile.mkdtemp(prefix="ms-home-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "20"})

import mock_tmdb  # noqa: E402
from app import db, homerows, server, settings, tmdb  # noqa: E402

n_ok = 0
U1 = {"id": 1, "is_admin": 1}
U2 = {"id": 2, "is_admin": 0}
TODAY = date.today()


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def d_ago(days):
    return (TODAY - timedelta(days=days)).isoformat()


# id, title, release date, rating, votes, genres, collection
FILMS = [
    (1, "Alpha", d_ago(30), 7.0, 900, ["Action", "Thriller"], None),
    (2, "Bravo", d_ago(200), 6.5, 300, ["Comedy"], None),
    (3, "Charlie", d_ago(600), 8.0, 5000, ["Drama"], None),
    (4, "Delta", d_ago(1500), 8.6, 20000, ["Drama", "Crime"], None),
    (5, "Obscure Gem", d_ago(900), 10.0, 3, ["Drama"], None),          # 10/10 with 3 votes
    (6, "Future Film", (TODAY + timedelta(days=60)).isoformat(), 0, 0, ["Action"], None),
    (7, "Saga One", d_ago(4000), 7.5, 8000, ["Science Fiction", "Action"], 77),
    (8, "Saga Two", d_ago(3000), 7.2, 6000, ["Science Fiction", "Action"], 77),
    (9, "Saga Three", d_ago(2000), 6.9, 5000, ["Science Fiction", "Action"], 77),
    (10, "Echo", d_ago(2500), 7.9, 4000, ["Science Fiction"], None),
    (11, "Foxtrot", d_ago(2600), 6.0, 2500, ["Romance", "Comedy"], None),
    (12, "Golf", d_ago(100), 5.5, 120, ["Horror"], None),
]


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies','/m',0,?)", (now,))
        for uid in (1, 2):
            c.execute("INSERT INTO users(id,username,pw_hash,is_admin,created_at) VALUES(?,?,'x',?,0)", (uid, "u%d" % uid, uid == 1))
        for i, t, rd, r, v, g, col in FILMS:
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,"
                      "size,mtime,duration) VALUES(?,1,?,'video','movie',?,?,?,?,?,'matched',1,1,6000)",
                      (i, "/m/%s.mkv" % t, t, t.lower(), int(rd[:4]), now - i * 100, 5000 + i))
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,genres,rating,vote_count,fetched_at,release_date,"
                      "collection_id,collection_name,cat_v) VALUES('movie',?,?,?,?,?,?,?,?,?,?,2)",
                      (5000 + i, t, int(rd[:4]), json.dumps(g), r, v, now, rd, col, "Saga Collection" if col else None))
            for x in g:
                c.execute("INSERT INTO movie_genres VALUES(?,?)", (5000 + i, x))
        # TMDB says: people who liked Saga One also like Echo, then Delta
        c.executemany("INSERT INTO movie_recs VALUES(?,?,?)", [(5007, 5010, 0), (5007, 5004, 1), (5004, 5003, 0)])
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,meta_status,size,mtime) "
                  "VALUES(13,1,'/m/unmatched.mkv','video','movie','Home Video','home video',?, 'nomatch',1,1)", (now + 50,))
    ids = lambda key, u=U1: [i["id"] for i in server.library_smart(1, key, u=u)["items"]]  # noqa: E731

    print("recently released")
    rr = ids("released")
    check(rr[:3] == [1, 12, 2], "newest release first: %s" % rr)
    check(6 not in rr, "future release dates excluded")
    rows = homerows.recently_released(1)
    recent = [i for i, r in rows if r == "recent"]
    check(recent == [1, 12, 2, 3], "last ~2 years: %s" % recent)
    check(len(rows) <= 12 and all(r == "older" for _i, r in rows[4:]), "topped up to 12 with next-newest, marked")
    check("4 from the last 2 years" in server.library_smart(1, "released", u=U1)["note"], "note says so")

    print("recently added")
    check(ids("added")[0] == 13, "by date added, unmatched files included")

    print("top movies (weighted rating)")
    tp = ids("top")
    check(tp[0] == 4, "Delta (8.6, 20k votes) first: %s" % tp)
    check(5 not in tp, "10/10 with 3 votes is not a top movie")
    check(tp.index(3) < tp.index(1), "8.0 x 5000 beats 7.0 x 900")
    wr = homerows._wr_fn([{"rating": 9.0, "vote_count": 60}, {"rating": 6.0, "vote_count": 60}])[0]
    check(abs(wr({"rating": 9.0, "vote_count": 60}) - 7.66) < 0.05, "few votes pulled toward the mean (Bayesian)")

    print("recommended -- no history yet")
    r0 = server.library_smart(1, "recommended", u=U1)
    check(r0["items"] and "haven't watched" in r0["note"], "fallback note: %s" % r0["note"])
    first6 = [i["id"] for i in r0["items"][:6]]
    check(6 not in first6[:3] and 5 not in first6[:3], "fallback favours well-known, well-rated films: %s" % first6)
    check(r0["items"][0]["reason"] == "Highly rated", "reason shown")
    check(ids("recommended") == [i["id"] for i in r0["items"]], "stable between loads")

    print("recommended -- after watching Saga One")
    with db.tx() as c:
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,7,5900,6000,1,?)", (now,))
    r1 = server.library_smart(1, "recommended", u=U1)
    rec = [i["id"] for i in r1["items"]]
    check(rec[0] == 8 and r1["items"][0]["reason"] == "Next in Saga Collection", "continue the franchise: %s" % r1["items"][0]["reason"])
    check(9 not in rec[:1] and rec.index(10) < rec.index(11), "TMDB recommendation (Echo) ranks above unrelated films")
    check(7 not in rec, "finished movie excluded")
    check(any(i.get("reason", "").startswith("Because you watched Saga One") for i in r1["items"]), "'Because you watched' reason")
    check("watched" in r1["note"], "history note")
    check(ids("recommended", U2)[0] != 8, "per user: user 2 has no history, gets the fallback")

    print("recommended -- in progress / continue watching")
    with db.tx() as c:
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,8,1200,6000,0,?)", (now + 5,))
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,3,5950,6000,0,?)", (now + 9,))
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,2,400,6000,0,?)", (now + 7,))
    rec = ids("recommended")
    check(8 not in rec and 9 not in rec[:1], "started Saga Two -> it moves to Continue watching; Saga Three waits until Two is finished: %s" % rec[:3])
    h = server.home(u=U1)
    cw = [i["id"] for i in h["continue"]]
    check(cw == [2, 8], "Continue watching: most recent first, finished-at-99%% excluded: %s" % cw)
    check(h["continue"][0]["position"] == 400 and h["continue"][0]["duration"], "progress for the bar / resume")
    check(server.home(u=U2)["continue"] == [], "no Continue watching row for a user with nothing in progress")
    keys = [r["key"] for r in h["libraries"][0]["smart_rows"]]
    check(keys == ["recommended", "released", "added", "top"], "home row order: %s" % keys)
    check(h["libraries"][0]["genre_rows"], "genre rows still follow")

    print("cache")
    row = db.row("SELECT sig FROM rec_cache WHERE user_id=1")
    ids("recommended")
    check(db.row("SELECT sig FROM rec_cache WHERE user_id=1")["sig"] == row["sig"], "cached (same signature on reload)")
    with db.tx() as c:
        c.execute("UPDATE progress SET watched=1 WHERE user_id=1 AND item_id=8")
    ids("recommended")
    check(db.row("SELECT sig FROM rec_cache WHERE user_id=1")["sig"] != row["sig"], "recomputed after a new watch")

    print("admin pins")
    server.pin_item(11, {"row": "top", "mode": 1}, u=U1)
    server.pin_item(4, {"row": "top", "mode": -1}, u=U1)
    tp = ids("top")
    check(tp[0] == 11 and 4 not in tp, "pinned first, hidden removed: %s" % tp[:3])
    server.pin_item(12, {"row": "recommended", "mode": 1}, u=U1)
    check(ids("recommended", U2)[0] == 12 and ids("recommended")[0] == 12, "recommended pin for everyone")
    server.pin_item(12, {"row": "recommended", "mode": 0}, u=U1)
    check(ids("recommended", U2)[0] != 12, "back to automatic")
    check(server.item_detail(11, u=U1)["pins"] == {"top": 1}, "item detail shows pins")
    try:
        server.pin_item(11, {"row": "nope", "mode": 1}, u=U1)
        check(False, "bad row rejected")
    except server.HTTPException:
        check(True, "bad row rejected")
    with db.tx() as c:
        c.execute("DELETE FROM items WHERE id=11")
    check(db.row("SELECT COUNT(*) n FROM home_pins WHERE item_id=11")["n"] == 0, "pins removed with the movie")

    print("TMDB recommendations stored by the background pass")
    settings.put("tmdb_enabled", "1")
    tmdb.fetch_details("movie", 1001, force=True)
    got = [r["rec_id"] for r in db.rows("SELECT rec_id FROM movie_recs WHERE tmdb_id=1001 ORDER BY rank")]
    check(got == [1003, 1002], "recommendations saved from the same details request: %s" % got)
    check(tmdb.CAT_VERSION >= 2, "category version >= 2 -> 1.4 libraries re-read once")
    try:
        server.library_smart(1, "bogus", u=U1)
        check(False, "unknown view 404")
    except server.HTTPException:
        check(True, "unknown view 404")
    print("\n%d checks passed" % n_ok)


if __name__ == "__main__":
    main()
