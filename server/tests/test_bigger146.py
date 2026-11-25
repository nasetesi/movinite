"""1.4.6: high-resolution artwork for the bigger details page -- a w780 poster fetched on first view and cached,
h632 cast photos (w185 photos cached by 1.4.3-1.4.5 are upgraded, and still used when TMDB is unreachable),
plus static checks of the new sizes.

    python3 tests/test_bigger146.py
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9564
TMP = tempfile.mkdtemp(prefix="ms-bigger-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "20"})

import mock_tmdb  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from app import config, db, server, tmdb  # noqa: E402
from app.version import __version__  # noqa: E402

n_ok = 0
U = {"id": 1, "username": "a", "is_admin": 1, "must_change_pw": 0}


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    check(tuple(map(int, __version__.split("."))) >= (1, 4, 6), "version 1.4.6 or later")
    check(int(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"]) >= 6, "schema 6 or later")
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies','/m',0,?)", (now,))
        c.execute("INSERT INTO users(id,username,pw_hash,is_admin,created_at) VALUES(1,'a','x',1,0)")
        for i, t in ((1, 1001), (2, 1002)):
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,size,mtime) "
                      "VALUES(?,1,?,'video','movie','T','t',2019,?,?,'matched',1,1)", (i, "/m/%d.mkv" % i, now, t))
    m = tmdb.fetch_details("movie", 1001)
    check(m and m["poster"] and m["poster_path"], "details cached with the w500 poster (%s)" % (m and m["poster_path"]))
    d = server.item_detail(1, u=U)
    check((d.get("poster_large") or "").startswith("/api/items/1/poster-large"), "details page gets a high-res poster link")
    big = tmdb._thumb_name(m["poster_path"], "w780")
    check(not (config.THUMB_DIR / big).exists(), "high-res poster not downloaded until someone views it")
    r = server.item_poster_large(1, u=U)
    check(Path(r.path).name == big and Path(r.path).exists() and big != m["poster"], "w780 poster downloaded on first view, cached separately")
    n_img = mock_tmdb.stats["images"]
    server.item_poster_large(1, u=U)
    check(mock_tmdb.stats["images"] == n_img, "second view served from the cache (no download)")
    # a movie with its own local poster.jpg keeps it (no TMDB high-res link)
    with db.tx() as c:
        c.execute("UPDATE items SET poster='0000000000000000000000000000000000000000.jpg', thumb='x' WHERE id=2")
    tmdb.fetch_details("movie", 1002)
    d2 = server.item_detail(2, u=U)
    check("poster_large" not in d2, "movie with a local poster: no TMDB high-res override")
    # unknown movie / no poster -> 404
    with db.tx() as c:
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,size,mtime) VALUES(3,1,'/m/3.mkv','video','movie','U','u',?,1,1)", (now,))
    try:
        server.item_poster_large(3, u=U); check(False, "404 expected")
    except HTTPException as e:
        check(e.status_code == 404, "no TMDB poster -> 404 (page keeps the normal one)")
    # cast photos: h632, upgrade of a cached w185 photo
    old = tmdb._thumb_name("/person77.jpg", "w185")
    (config.THUMB_DIR / old).write_bytes(b"\xff\xd8old")
    with db.tx() as c:
        c.execute("INSERT INTO people(id,name,profile_path,photo,updated_at) VALUES(77,'Old Photo','/person77.jpg',?,0)", (old,))
        c.execute("INSERT INTO people(id,name,profile_path,photo,updated_at) VALUES(78,'Offline','/person78.jpg',?,0)",
                  (tmdb._thumb_name("/person78.jpg", "w185"),))
    (config.THUMB_DIR / tmdb._thumb_name("/person78.jpg", "w185")).write_bytes(b"\xff\xd8old")
    n = tmdb.person_photo(77)
    check(n == tmdb._thumb_name("/person77.jpg", "h632"), "cached w185 photo upgraded to h632 on first view")
    check(db.row("SELECT photo FROM people WHERE id=77")["photo"] == n, "people.photo now points at the h632 file")
    n_img = mock_tmdb.stats["images"]
    tmdb.person_photo(77)
    check(mock_tmdb.stats["images"] == n_img, "h632 photo then served from the cache")
    real = config.TMDB_IMAGE_BASE
    config.TMDB_IMAGE_BASE = "http://127.0.0.1:9/t/p"      # TMDB unreachable
    try:
        t0 = time.time()
        check(tmdb.person_photo(78) == tmdb._thumb_name("/person78.jpg", "w185"), "TMDB unreachable: the old w185 photo is still shown")
        t2 = time.time(); tmdb.person_photo(78)
        check(time.time() - t2 < 0.5, "and the next view does not wait for TMDB again (%.2fs)" % (time.time() - t2))
        with db.tx() as c:
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,tmdb_id,meta_status,size,mtime) VALUES(4,1,'/m/4.mkv','video','movie','V','v',?,1003,'matched',1,1)", (now,))
        config.TMDB_IMAGE_BASE = real
        tmdb.fetch_details("movie", 1003)
        config.TMDB_IMAGE_BASE = "http://127.0.0.1:9/t/p"
        try:
            server.item_poster_large(4, u=U); check(False, "404 expected")
        except HTTPException as e:
            check(e.status_code == 404, "TMDB unreachable: high-res poster 404 -> page shows the cached w500 one")
        t1 = time.time()
        try:
            server.item_poster_large(4, u=U)
        except HTTPException:
            pass
        check(time.time() - t1 < 0.5, "and it does not retry TMDB again for 10 minutes (%.2fs)" % (time.time() - t1))
    finally:
        config.TMDB_IMAGE_BASE = real
    # static: sizes
    css = (HERE.parent / "app/static/style.css").read_text()
    js = (HERE.parent / "app/static/app.js").read_text()
    check(".detail .poster:not(.landscape):not(.square){width:clamp(240px,34.4vw,550px)}" in css, "details poster up to 550 px")
    check(".detail .overview{font-size:19px;line-height:1.6" in css, "description 19 px, line height 1.6")
    check(".cast-strip{grid-auto-columns:186px" in css, "cast photos 186 px (was 124)")
    check(".strip.sim{grid-auto-columns:clamp(190px,20.6vw,330px)" in css, "similar posters up to 330 px")
    check("it.poster_large && img === it.poster" in js, "page layers the high-res poster over the cached one (falls back if it fails)")
    print("ALL %d BIGGER-PAGE CHECKS PASSED" % n_ok)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
