"""1.5.5: Continue watching and the Recently added rows on the home page (web, phone and the Android app, which shows
the same page) list only Movies and TV Shows libraries.

    python3 tests/test_home155.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["MS_DATA_DIR"] = tempfile.mkdtemp(prefix="ms-home155-") + "/data"
from app import auth, db, server  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    db.migrate()
    now = int(time.time())
    uid = auth.create_user("viewer155", "ViewPass14!", is_admin=False)
    u = db.row("SELECT * FROM users WHERE id=?", (uid,))
    ids = {}
    with db.tx() as c:
        for lid, name, kind in ((1, "Movies", "movies"), (2, "TV Shows", "tv"), (3, "Home Videos", "other"), (4, "Music", "music")):
            c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(?,?,?,?,0,?)",
                      (lid, name, kind, "/x/%d" % lid, now))
        for key, lid, mt, kind, extra in (("movie", 1, "video", "movie", {}), ("episode", 2, "video", "episode", {"show": "Show", "season": 1, "episode": 1}),
                                          ("homevid", 3, "video", "other", {}), ("song", 4, "audio", "track", {"artist": "A", "album": "B"})):
            cols = {"library_id": lid, "path": "/x/%s.mkv" % key, "media_type": mt, "kind": kind, "title": key.title(),
                    "sort_title": key, "duration": 3600, "size": 1, "mtime": 1, "added_at": now, **extra}
            cur = c.execute("INSERT INTO items(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(cols.values()))
            ids[key] = cur.lastrowid
        for key in ("movie", "episode", "homevid"):
            c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(?,?,?,?,0,?)",
                      (uid, ids[key], 600, 3600, now))
    h = server.home(u)
    cont = {i["id"] for i in h["continue"]}
    check(cont == {ids["movie"], ids["episode"]}, "Continue watching: the movie and the episode, not the home video")
    kinds = [L["library"]["kind"] for L in h["libraries"]]
    check(kinds == ["movies", "tv"], "Recently added rows only for Movies and TV Shows (got %s)" % kinds)
    shown = {i["id"] for L in h["libraries"] for i in L.get("items") or []}
    check(ids["homevid"] not in shown and ids["song"] not in shown, "no home video or music in the home rows")
    check(ids["movie"] in shown and ids["episode"] in shown, "the new movie and episode are in Recently added")
    ml = server.mylist(u)
    check({i["id"] for i in ml["continue"]} == {ids["movie"], ids["episode"]}, "My List (phone) in-progress list follows the same rule")
    js = (HERE.parent / "app" / "static" / "app.js").read_text()
    check("Movies and TV shows appear here" in js, "home page explains where other libraries are when it is empty")
    print("FAILS: %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
