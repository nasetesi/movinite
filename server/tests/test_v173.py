"""1.7.3: a folder poster saved for an earlier, wrong match no longer hides the poster of the current match.

Reproduces "Adore (2013)" on the GPU server: the file was first matched to the wrong film ("Je t'adore", TMDB
1590299); artwork saving wrote poster.jpg + movie.nfo (marked "written by Media Server") into its folder on the
share; the user later matched it by hand to Adoration (111190), but the folder poster -- the wrong film's --
still won over the TMDB poster on one copy, and that copy was the one shown.  Here 1099 plays "Je t'adore" and
1002 plays "Adoration" (mock TMDB ids).

    python3 tests/test_v173.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9573
TMP = tempfile.mkdtemp(prefix="ms-v173-")
os.environ.update({
    "MS_DATA_DIR": TMP + "/data",
    "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
    "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT,
    "MS_TMDB_KEY": "GOODKEY",
    "MS_TMDB_MAX_RPS": "10",
})

import mock_tmdb  # noqa: E402
from app import artwork, auth, config, db, folderart, media, scanner, server, tmdb  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []
U = {"id": 1, "is_admin": 1}
OLD, RIGHT = 1099, 1002
NAME = "Adore (2013) [1080p]"


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def own_nfo(tid, title="Je t'adore"):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            "<!-- written by Media Server from TMDB (themoviedb.org) -->\n<movie>\n  <title>%s</title>\n"
            "  <year>2013</year>\n  <uniqueid type=\"tmdb\" default=\"true\">%d</uniqueid>\n  <tmdbid>%d</tmdbid>\n"
            "</movie>\n" % (title, tid, tid))


def make_folder(root, nfo_text):
    d = Path(root) / "Movies" / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / (NAME + ".mp4")).write_bytes(b"")
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x300",
                    "-frames:v", "1", str(d / "poster.jpg")], check=True)
    (d / "movie.nfo").write_text(nfo_text, encoding="utf-8")
    return d


def add(item_id, lib, path, tid, status, poster, thumb):
    with db.tx() as c:
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,width,height,bitrate,size,"
                  "mtime,added_at,tmdb_id,meta_status,meta_confidence,poster,thumb,duration) "
                  "VALUES(?,?,?,'video','movie','Adore','adore',2013,1920,808,8000000,1763045512,1,?,?,?,?,?,?,7200)",
                  (item_id, lib, str(path), int(time.time()) - item_id, tid, status, 1.0, poster, thumb))


def reset(tid=OLD, status="matched"):
    """Back to the data as 1.7.1 left it: art columns unknown, local poster on the Sunset copy only."""
    with db.tx() as c:
        c.execute("UPDATE items SET tmdb_id=?, meta_status=?, art_poster=NULL, art_tmdb=NULL WHERE id IN (30,2052)",
                  (tid, status))
        c.execute("UPDATE items SET poster=thumb WHERE id=30")
        c.execute("UPDATE items SET poster=? WHERE id=2052", (LOCAL,))


def main():
    global LOCAL
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 3), "version is 1.7.3 or later")
    srv = mock_tmdb.serve(PORT)
    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    cols = {r["name"] for r in db.rows("PRAGMA table_info(items)")}
    check({"art_poster", "art_tmdb"} <= cols, "migration adds items.art_poster / items.art_tmdb")
    now = int(time.time())
    s1, s2 = TMP + "/waimea", TMP + "/sunset"
    d1, d2 = make_folder(s1, own_nfo(OLD)), make_folder(s2, own_nfo(OLD))
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at,sort_order) VALUES(1,'Waimea Movies','movies',?,0,?,2)", (s1 + "/Movies", now))
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at,sort_order) VALUES(2,'Sunset Movies','movies',?,0,?,1)", (s2 + "/Movies", now))
    frame1, frame2 = "5" * 40 + ".jpg", "e" * 40 + ".jpg"
    for f in (frame1, frame2):
        (config.THUMB_DIR / f).write_bytes(b"frame")
    LOCAL = media.make_image_thumb(str(d2 / "poster.jpg"))
    check(bool(LOCAL), "folder poster.jpg thumbnailed (the wrong film's poster)")
    # Waimea copy scanned before poster.jpg existed (poster == frame); Sunset copy scanned after (local poster)
    add(30, 1, d1 / (NAME + ".mp4"), OLD, "matched", frame1, frame1)
    add(2052, 2, d2 / (NAME + ".mp4"), OLD, "matched", LOCAL, frame2)
    tmdb.fetch_details("movie", OLD, force=True)
    tmdb.fetch_details("movie", RIGHT, force=True)
    right = tmdb.cached("movie", RIGHT)["poster"]
    check(right and right != LOCAL, "Adoration's TMDB poster is cached and differs from the folder poster")

    print("the 1.7.1 situation: matched by hand, but the old folder poster still wins (art not checked yet)")
    reset(RIGHT, "manual")
    d = server.item_detail(2052, u=U)
    check(d["poster"] == LOCAL and not d.get("poster_large"),
          "reproduced: Sunset copy shows the folder poster of the old match and no large TMDB poster")
    check(server.item_detail(30, u=U)["poster"] == right, "while the Waimea copy (no folder poster picked up) is right")

    print("startup backfill (existing libraries) fixes it without touching the share")
    before = {p: p.stat().st_mtime_ns for p in list(d1.iterdir()) + list(d2.iterdir())}
    n = folderart.backfill(wait_s=0)
    check(n >= 1, "backfill checked %d movie(s)" % n)
    r = db.row("SELECT poster, art_poster, art_tmdb FROM items WHERE id=2052")
    check(r["art_poster"] == LOCAL and r["art_tmdb"] == OLD, "Sunset copy: art_poster kept, art_tmdb = %s (from movie.nfo)" % r["art_tmdb"])
    d = server.item_detail(2052, u=U)
    check(d["poster"] == right, "details page now shows Adoration's TMDB poster")
    check(d.get("poster_large") == "/api/items/2052/poster-large?v=%s" % right, "large poster offered with ?v=: %s" % d.get("poster_large"))
    check(before == {p: p.stat().st_mtime_ns for p in before} and len(list(d2.iterdir())) == 3,
          "nothing in either folder was written or removed")
    check(folderart.backfill(wait_s=0) == 0, "second pass has nothing to do")

    print("Fix match on pre-1.7.3 data takes effect immediately (no backfill needed)")
    reset(OLD, "matched")
    check(server.item_detail(2052, u=U)["poster"] == LOCAL, "old match: the folder poster (it is that film's) is shown")
    r = server.match_item(30, {"tmdb_id": RIGHT}, U)       # matched from the OTHER copy, like the user did
    check(r.get("ok") and r.get("matched"), "Fix match from the Waimea copy succeeded")
    for iid in (30, 2052):
        d = server.item_detail(iid, u=U)
        check(d["tmdb_id"] == RIGHT and d["poster"] == right and (d.get("poster_large") or "").endswith("?v=" + right),
              "item %d: Adoration + its TMDB poster + cache-busted large poster" % iid)

    print("cards, search and the library grid use the same poster")
    lib = server.library_items(2, u=U)
    card = [i for i in lib["items"] if i["id"] == 2052]
    check(card and card[0]["poster"] == right, "Sunset library grid card shows the TMDB poster")
    res = server.search("Ador", U)
    hits = [i for i in res.get("items", []) if i.get("tmdb_id") == RIGHT]
    check(len(hits) == 1 and hits[0]["poster"] == right, "search: one Adoration card with the TMDB poster")

    print("matching back to the film the folder art is for shows the folder poster again; unmatched keeps it")
    server.match_item(2052, {"tmdb_id": OLD}, U)
    check(server.item_detail(2052, u=U)["poster"] == LOCAL, "match = .nfo film -> folder poster")
    server.match_item(2052, {"unmatch": True}, U)
    check(db.row("SELECT poster FROM items WHERE id=2052")["poster"] == LOCAL, "use file names -> folder poster kept")

    print("folder poster with a matching / no .nfo is still preferred over TMDB")
    (d2 / "movie.nfo").write_text(own_nfo(RIGHT, "Adoration"), encoding="utf-8")
    server.match_item(2052, {"tmdb_id": RIGHT}, U)
    check(server.item_detail(2052, u=U)["poster"] == LOCAL, ".nfo names the current match -> folder poster wins")
    (d2 / "movie.nfo").unlink()
    server.match_item(2052, {"tmdb_id": OLD}, U)
    check(server.item_detail(2052, u=U)["poster"] == LOCAL, "no .nfo -> folder poster wins (as before 1.7.3)")
    (d2 / "movie.nfo").write_text(own_nfo(OLD), encoding="utf-8")

    print("scanner records the folder art for new files")
    lib2 = db.row("SELECT * FROM libraries WHERE id=2")
    p = d2 / (NAME + ".mp4")
    info = scanner.build_item(lib2, Path(lib2["path"]), p, 0, 1.0)
    check(info.get("art_tmdb") == OLD and info.get("art_poster") == info.get("poster") and info.get("poster"),
          "build_item: art_poster = folder poster, art_tmdb = %s" % info.get("art_tmdb"))
    with db.tx() as c:
        c.execute("UPDATE items SET tmdb_id=?, poster=?, art_poster=?, art_tmdb=? WHERE id=2052",
                  (RIGHT, info["poster"], info["art_poster"], info["art_tmdb"]))   # what the scan commit writes
    scanner._finish(lib2, {"started_at": time.time()}, "error", "test")
    check(db.row("SELECT poster FROM items WHERE id=2052")["poster"] == frame2,
          "after a scan the folder poster of another film is set aside again (poster = frame, TMDB overlays)")

    print("artwork saving: replaces its OWN files left from an old match, never other tools' files")
    libw = dict(lib2, art_write=1, art_fanart=0, art_nfo=1, art_overwrite=0)
    it = db.row("SELECT * FROM items WHERE id=2052")
    sib, nested = artwork._siblings(2)
    meta = tmdb.cached("movie", RIGHT)
    acts = {a["what"]: a["action"] for a in artwork.plan_item(it, libw, meta, sib, nested)}
    check(acts == {"poster": "overwrite", "nfo": "overwrite"}, "own poster.jpg + movie.nfo for 1099 -> overwrite: %s" % acts)
    (d2 / "movie.nfo").write_text("<movie><title>x</title><uniqueid type=\"tmdb\">%d</uniqueid></movie>" % OLD)
    acts = {a["what"]: a["action"] for a in artwork.plan_item(it, libw, meta, sib, nested)}
    check(acts == {"poster": "skip", "nfo": "skip"}, "another tool's .nfo (no Media Server mark) -> left alone: %s" % acts)
    (d2 / "movie.nfo").write_text(own_nfo(RIGHT, "Adoration"), encoding="utf-8")
    acts = {a["what"]: a["action"] for a in artwork.plan_item(it, libw, meta, sib, nested)}
    check(acts == {"poster": "skip", "nfo": "skip"}, "own files for the current match -> already there: %s" % acts)

    try:
        srv.shutdown()
    except Exception:
        pass


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
