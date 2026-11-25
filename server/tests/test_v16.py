"""1.6: admin-set library order (server-wide), default order by type (Movies, TV Shows, Other videos, Music),
settings tabs in the user's order.

    python3 tests/test_v16.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-v16-")
os.environ["MS_DATA_DIR"] = TMP + "/data"
from app import auth, db, liborder, server  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def names():
    return [l["name"] for l in server.list_libraries(None)]


def raw_insert(name, kind):
    with db.tx() as c:
        c.execute("INSERT INTO libraries(name,kind,path,scan_interval_h,created_at) VALUES(?,?,?,0,?)",
                  (name, kind, "/x/" + name, int(time.time())))


def main():
    # pure placement rule
    o = [(1, "movies"), (2, "tv"), (3, "music")]
    check([i for i, _ in liborder.place(o, (9, "other"))] == [1, 2, 9, 3], "other goes between TV and Music")
    check([i for i, _ in liborder.place(o, (9, "movies"))] == [1, 9, 2, 3], "second movie library goes after the first")
    check([i for i, _ in liborder.place([(1, "movies"), (3, "music"), (4, "movies")], (9, "tv"))] == [1, 9, 3, 4],
          "custom order kept: with no TV library yet, a new one goes right before the first later type (Music)")
    check([i for i, _ in liborder.place([(2, "tv"), (1, "movies")], (9, "tv"))] == [2, 9, 1], "custom order: new TV right after the existing TV")
    check(liborder.rank("photos") == 9, "unknown types go last")

    # migration: libraries from an older version (no sort_order) like the GPU server's, inserted in a mixed order
    db.migrate()
    for n, k in (("Music", "music"), ("Home Videos", "other"), ("TV Shows", "tv"), ("Movies", "movies"), ("4K Movies", "movies")):
        raw_insert(n, k)
    with db.tx() as c:
        c.execute("UPDATE libraries SET sort_order=NULL")
    db.migrate()        # what update.sh runs
    check(names() == ["4K Movies", "Movies", "TV Shows", "Home Videos", "Music"], "migration orders by type, then name (%s)" % names())
    db.migrate()
    check(names() == ["4K Movies", "Movies", "TV Shows", "Home Videos", "Music"], "migration is idempotent")

    # admin order
    ids = {l["name"]: l["id"] for l in server.list_libraries(None)}
    new = [ids["Music"], ids["TV Shows"], ids["Movies"], ids["4K Movies"], ids["Home Videos"]]
    out = server.order_libraries({"ids": new}, None)
    check([l["id"] for l in out] == new, "PUT /api/libraries/order saves the admin order")
    check(names() == ["Music", "TV Shows", "Movies", "4K Movies", "Home Videos"], "GET /api/libraries follows it")
    for bad in ({"ids": new[:-1]}, {"ids": new + [new[0]]}, {"ids": "x"}, {"ids": new[:-1] + [999]}):
        try:
            server.order_libraries(bad, None)
            check(False, "bad order rejected %s" % bad)
        except server.HTTPException as e:
            check(e.status_code == 400, "bad order rejected (%s)" % str(bad)[:40])
    check(names() == ["Music", "TV Shows", "Movies", "4K Movies", "Home Videos"], "a rejected order changes nothing")

    # adding libraries through the API keeps the custom order and slots the new one by type
    d = Path(TMP) / "media"
    for sub in ("tv2", "mov3", "other2", "music2"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    server.add_library({"name": "Kids TV", "kind": "tv", "source": {"type": "local", "path": str(d / "tv2")}, "scan_interval_h": 0}, None)
    check(names() == ["Music", "TV Shows", "Kids TV", "Movies", "4K Movies", "Home Videos"], "new TV library right after the TV library (%s)" % names())
    server.add_library({"name": "Classics", "kind": "movies", "source": {"type": "local", "path": str(d / "mov3")}, "scan_interval_h": 0}, None)
    check(names()[-2:] == ["Classics", "Home Videos"] and names().index("Classics") == 5, "new movie library after the last movie library")
    # a fresh server: libraries added in any order come out Movies, TV, Other videos, Music
    with db.tx() as c:
        c.execute("DELETE FROM libraries")
    for n, k, sub in (("Songs", "music", "music2"), ("Clips", "other", "other2"), ("Shows", "tv", "tv2"), ("Films", "movies", "mov3")):
        server.add_library({"name": n, "kind": k, "source": {"type": "local", "path": str(d / sub)}, "scan_interval_h": 0}, None)
    check(names() == ["Films", "Shows", "Clips", "Songs"], "fresh server: Movies, TV Shows, Other videos, Music (%s)" % names())
    # home rows follow the order too (movies before tv)
    uid = auth.create_user("viewer156", "ViewPass14!", is_admin=False)
    h = server.home(db.row("SELECT * FROM users WHERE id=?", (uid,)))
    check([L["library"]["name"] for L in h["libraries"]] == ["Films", "Shows"], "home rows in library order")

    js = (HERE.parent / "app" / "static" / "app.js").read_text()
    want = ["libraries", "scans", "sounds", "metadata", "transcoding", "users", "account", "system"]
    i0 = js.index("const ALL_TABS")
    seg = js[i0:js.index("];", i0)]
    got = [w for w in want if '["%s"' % w in seg]
    pos = [seg.index('["%s"' % w) for w in want]
    check(got == want and pos == sorted(pos), "Settings tabs left to right: Libraries, Scan activity, Poster Sounds, Metadata, Transcoding, Users, My account, System")
    check("tab = tabs[0][0]" in js, "a hidden or unknown tab opens the first visible tab")
    check('"/api/libraries/order"' in js and "data-up" in js and "draggable" in js, "reorder UI: drag and drop plus up / down buttons")
    # two-part versions (1.6) from now on, a third digit only for quick fixes (1.6.1): update.sh compares numerically
    import subprocess
    up = (HERE.parent / "update.sh").read_text()
    vc = up[up.index("vcmp() {"):]
    vc = vc[:vc.index("\n}\n") + 3]
    from app.version import __version__
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 6), "version is 1.6 or later")
    for a, b, want in (("1.6", "1.5.5", "1"), ("1.6.1", "1.6", "1"), ("1.6", "1.6.0", "0"), ("1.5.5", "1.6", "-1"), ("1.10", "1.9", "1")):
        got = subprocess.run(["bash", "-c", vc + '\nvcmp "$1" "$2"', "x", a, b], capture_output=True, text=True).stdout.strip()
        check(got == want, "update.sh vcmp %s vs %s = %s" % (a, b, got))
    srt = subprocess.run(["sort", "-V"], input="media-server-ver1.6.1.tar.gz\nmedia-server-ver1.6.tar.gz\nmedia-server-ver1.5.5.tar.gz\n",
                         capture_output=True, text=True).stdout.split()
    check(srt[-1] == "media-server-ver1.6.1.tar.gz" and srt[0] == "media-server-ver1.5.5.tar.gz", "newest-tarball pick (sort -V): 1.5.5 < 1.6 < 1.6.1")
    print("FAILS: %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
