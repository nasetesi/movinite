"""1.7.1: after Fix match / Accept, the details poster updates (cache-busted large-poster URL)
and every version and copy of the film follows the new match.

    python3 tests/test_v171.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9571
TMP = tempfile.mkdtemp(prefix="ms-v171-")
os.environ.update({
    "MS_DATA_DIR": TMP,
    "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
    "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT,
    "MS_TMDB_KEY": "GOODKEY",
    "MS_TMDB_MAX_RPS": "10",
})

import mock_tmdb  # noqa: E402
from app import auth, config, db, server, settings, titles, tmdb  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []
U = {"id": 1, "is_admin": 1}


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def add_movie(lib, title, year, w, h, item_id, tmdb_id=None, status=None, confidence=None,
              poster=None, thumb=None, edition=None, candidate=None):
    now = int(time.time())
    with db.tx() as c:
        c.execute(
            "INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,edition,width,height,"
            "bitrate,size,mtime,added_at,tmdb_id,meta_status,meta_confidence,meta_candidate,poster,thumb,duration) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, lib, "/srv/x/%d/%s-%d.mkv" % (lib, title, item_id), "video", "movie", title, title.lower(),
             year, edition, w, h, 10_000_000, 1_000_000, 1, now, tmdb_id, status, confidence, candidate,
             poster, thumb, 7200))
    return item_id


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 1), "version is 1.7.1 or later")
    js = (HERE.parent / "app/static/app.js").read_text()
    check("it.poster_large && img === it.poster" in js and "url('${it.poster_large}')" in js,
          "details page uses the server's poster_large URL as-is (query string included)")
    check('function thumbUrl(n) { return n ? "/api/thumb/" + n : ""; }' in js,
          "card thumbs stay content-addressed (/api/thumb/<sha>.jpg)")

    srv = mock_tmdb.serve(PORT)
    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO shares(id,name,kind,remote,mount_point,created_at,allow_write) VALUES(1,'Waimea','smb','//w/M','',?,0)", (now,))
        c.execute("INSERT INTO shares(id,name,kind,remote,mount_point,created_at,allow_write) VALUES(2,'Sunset','smb','//s/M','',?,0)", (now,))
        c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at,sort_order) VALUES(1,'Waimea Movies','movies','/srv/x/1',1,0,?,1)", (now,))
        c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at,sort_order) VALUES(2,'Sunset Movies','movies','/srv/x/2',2,0,?,2)", (now,))

    # a unique fake frame-grab used as the "old" poster (poster == thumb, so TMDB art can overlay)
    frame = "a" * 40 + ".jpg"
    (config.THUMB_DIR / frame).write_bytes(b"old-frame")

    print("movie_match_ids: versions and copies, even when match state differs")
    # 4K on Waimea: low-confidence (needs review) match to the 1985 decoy
    # 1080p on Waimea and both files on Sunset: still unmatched / review (no tmdb_id)
    add_movie(1, "Another Film", 2021, 3840, 2160, 11, tmdb_id=1099, status="matched", confidence=0.6,
              poster=frame, thumb=frame)
    add_movie(1, "Another Film", 2021, 1920, 1080, 12, status="review", poster=frame, thumb=frame, candidate=1002)
    add_movie(2, "Another Film", 2021, 3840, 2160, 21, status="review", poster=frame, thumb=frame)
    add_movie(2, "Another Film", 2021, 1920, 1080, 22, status="review", poster=frame, thumb=frame)
    # a different film must not be pulled in
    add_movie(1, "Remux Test", 2022, 1920, 1080, 31, status="review", poster=frame, thumb=frame)
    got = titles.movie_match_ids(11)
    check(got == [11, 12, 21, 22], "4K (wrong match) + 1080p + both copies on the other share: %s" % got)
    check(titles.movie_match_ids(12) == [11, 12, 21, 22], "starting from the unmatched 1080p finds the matched 4K too")
    check(titles.movie_match_ids(31) == [31], "a different title is not included")

    print("Fix match: poster updates and the large-poster URL is cache-busted")
    check(settings.tmdb_enabled(), "TMDB enabled for the test")
    # the 4K currently shows the decoy's poster (low-confidence automatic match)
    tmdb.fetch_details("movie", 1099, force=True)
    tmdb.enrich([db.row("SELECT * FROM items WHERE id=11")])
    decoy = tmdb.cached("movie", 1099)
    check(decoy and decoy["poster"] and (config.THUMB_DIR / decoy["poster"]).is_file(), "decoy poster is cached")
    before = server.item_detail(11, u=U)
    check(before["tmdb_id"] == 1099 and before["poster"] == decoy["poster"],
          "before: details page shows the (wrong) decoy poster")
    check(before.get("needs_review"), "before: flagged as needs review")
    check(before.get("poster_large") == "/api/items/11/poster-large?v=%s" % decoy["poster"],
          "before: poster_large carries ?v= the decoy file: %s" % before.get("poster_large"))

    r = server.match_item(11, {"tmdb_id": 1002}, U)
    check(r.get("ok") and r.get("matched"), "Fix match to TMDB 1002 succeeded")
    after = server.item_detail(11, u=U)
    right = tmdb.cached("movie", 1002)
    check(right and right["poster"] and right["poster"] != decoy["poster"],
          "the correct film has a different cached poster file")
    check(after["tmdb_id"] == 1002 and after["match_status"] == "manual" and not after.get("needs_review"),
          "after: item is a confirmed manual match to 1002")
    check(after["poster"] == right["poster"] and after["poster"] != frame and after["poster"] != decoy["poster"],
          "after: details poster is the correct TMDB art, not the frame-grab or the decoy")
    check(after.get("poster_large") == "/api/items/11/poster-large?v=%s" % right["poster"],
          "after: poster_large ?v= changed with the new poster: %s" % after.get("poster_large"))
    check(before["poster_large"] != after["poster_large"],
          "the large-poster URL changed, so the week-long browser cache cannot keep the old image")

    print("versions and copies follow the match")
    rows = {r["id"]: r for r in db.rows("SELECT id, tmdb_id, meta_status FROM items WHERE id IN (11,12,21,22,31)")}
    check(all(rows[i]["tmdb_id"] == 1002 and rows[i]["meta_status"] == "manual" for i in (11, 12, 21, 22)),
          "4K, 1080p and both copies on the other share now match 1002")
    check(rows[31]["tmdb_id"] is None and rows[31]["meta_status"] == "review", "the other film is untouched")
    for iid in (12, 21, 22):
        d = server.item_detail(iid, u=U)
        check(d["poster"] == right["poster"] and "?v=%s" % right["poster"] in (d.get("poster_large") or ""),
              "item %d also shows the new poster and a cache-busted large URL" % iid)

    print("Accept suggestion also updates the poster")
    add_movie(1, "The Big Test Movie", 2019, 1920, 1080, 41, status="review",
              poster=frame, thumb=frame, candidate=1001)
    r = server.match_item(41, {"accept_candidate": True}, U)
    check(r.get("ok"), "accept_candidate succeeded")
    accepted = server.item_detail(41, u=U)
    big = tmdb.cached("movie", 1001)
    check(accepted["tmdb_id"] == 1001 and accepted["poster"] == big["poster"] and accepted["poster"] != frame,
          "accepting the suggestion swaps the frame-grab for the TMDB poster")
    check(accepted.get("poster_large") == "/api/items/41/poster-large?v=%s" % big["poster"],
          "accepted match also cache-busts poster_large")

    print("a review item with only a frame-grab (no prior TMDB id) gets a poster after Fix match")
    add_movie(1, "Remux Test", 2022, 1280, 720, 51, status="review", poster=frame, thumb=frame)
    before51 = server.item_detail(51, u=U)
    check(before51.get("poster") == frame and not before51.get("poster_large") and before51.get("tmdb_id") is None,
          "before: review item shows the frame-grab and has no large poster")
    server.match_item(51, {"tmdb_id": 1003}, U)
    after51 = server.item_detail(51, u=U)
    remux = tmdb.cached("movie", 1003)
    check(after51["poster"] == remux["poster"] and after51.get("poster_large", "").endswith("?v=%s" % remux["poster"]),
          "after: TMDB poster is shown, with a cache-busted large URL")

    try:
        srv.shutdown()
    except Exception:
        pass


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
