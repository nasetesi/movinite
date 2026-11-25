"""1.4: movie categories -- genre index, collections, age ratings, the background backfill, filters and tags.

    python3 tests/test_categories.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9561
TMP = tempfile.mkdtemp(prefix="ms-cat-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "20"})

import mock_tmdb  # noqa: E402
from app import db, server, settings, tmdb  # noqa: E402

n_ok = 0
U = {"id": 1, "is_admin": 1}


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
        time.sleep(0.05)
    raise AssertionError("metadata run timed out: %s" % tmdb.status.get(lib_id))


def add_item(i, title, year, tmdb_id=None, status=None, lib=1):
    with db.tx() as c:
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,"
                  "size,mtime) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,1)",
                  (i, lib, "/m/%s (%s)/%s.%d.mkv" % (title, year, title, i), "video", "movie", title, title.lower(), year,
                   int(time.time()) - i, tmdb_id, status))


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    settings.put("tmdb_enabled", "1")
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies','/m',0,?)",
                  (int(time.time()),))
        c.execute("INSERT INTO users(id,username,pw_hash,is_admin,created_at) VALUES(1,'admin','x',1,0)")

    print("schema / upgrade from 1.3.x")
    check(db.SCHEMA_VERSION >= 4, "schema version %d" % db.SCHEMA_VERSION)
    cols = {r[1] for r in db.connect().execute("PRAGMA table_info(metadata)")}
    check({"collection_id", "collection_name", "certification", "cat_v"} <= cols, "new metadata columns")
    # a 1.3.1 database: metadata cached with genres JSON, no genre index, no category stamp
    add_item(1, "The Big Test Movie", 2019, 1001, "matched")
    add_item(2, "Another Film", 2021, 1002, "manual")        # chosen with Fix match
    add_item(3, "Remux Test", 2022, 1003, "matched")
    add_item(4, "Unknown Thing", 2005, None, "nomatch")
    add_item(5, "Old Decoy", 1985, 1099, "matched")
    with db.tx() as c:
        for tid, title, year, genres in ((1001, "The Big Test Movie", 2019, ["Drama", "Science Fiction"]),
                                         (1002, "Another Film", 2021, ["Thriller"]),
                                         (1003, "Remux Test", 2022, ["Documentary"]), (1099, "Another Film", 1985, [])):
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,genres,rating,fetched_at,release_date) "
                      "VALUES('movie',?,?,?,?,7,?,?)", (tid, title, year, json.dumps(genres), int(time.time()),
                                                         "%d-01-01" % year))
        c.execute("DELETE FROM movie_genres")
        c.execute("UPDATE items SET meta_checked_at=? WHERE id=4", (int(time.time()),))   # looked up recently
        c.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    db.migrate()
    g = {r["genre"] for r in db.rows("SELECT genre FROM movie_genres")}
    check(g == {"Drama", "Science Fiction", "Thriller", "Documentary"}, "upgrade fills the genre index from the cache: %s" % g)
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] == str(db.SCHEMA_VERSION), "stamped current schema")
    db.migrate()
    check(db.row("SELECT COUNT(*) n FROM movie_genres")["n"] == 4, "migrate is idempotent")
    f = server.library_genres(1, u=U)
    check([x["name"] for x in f["genres"]][:1] and {x["name"]: x["n"] for x in f["genres"]}["Drama"] == 1,
          "genre counts work before the backfill")

    print("background backfill (pending -> resume -> categories phase)")
    pend = tmdb.pending_count(1)
    check(pend == 4, "4 matched/manual movies need categories: %d" % pend)
    calls0 = mock_tmdb.stats["api"]
    tmdb._last_resume.clear()
    check(tmdb.resume_pending() == [1], "resume_pending queues the library (runs after an update)")
    st = wait_meta(1)
    check(st["state"] == "done" and st.get("phase") == "categories", "ran as the categories phase: %s" % st.get("phase"))
    check(st["total"] == 4 and st["done"] == 4, "4 lookups, shown with done/total: %s/%s" % (st["done"], st["total"]))
    calls = mock_tmdb.stats["api"] - calls0
    check(calls <= 4, "about one API call per movie: %d" % calls)
    check(tmdb.pending_count(1) == 0, "nothing pending afterwards")
    tmdb._last_resume.clear()
    check(tmdb.resume_pending() == [], "no re-queue once done")
    it2 = db.row("SELECT meta_status, tmdb_id FROM items WHERE id=2")
    check(it2["meta_status"] == "manual" and it2["tmdb_id"] == 1002, "Fix-match choice kept")
    m = db.row("SELECT * FROM metadata WHERE tmdb_id=1001")
    check(m["collection_id"] == 9001 and m["collection_name"] == "Test Pattern Collection", "collection stored")
    check(m["certification"] == "PG-13" and m["cat_v"] == tmdb.CAT_VERSION, "US age rating stored: %s" % m["certification"])
    c9 = db.row("SELECT * FROM collections WHERE id=9001")
    check(c9 and c9["poster"], "collection poster cached")
    check(db.row("SELECT certification c FROM metadata WHERE tmdb_id=1002")["c"] is None, "no rating -> NULL")

    print("certification picks the UI language's country")
    settings.put("tmdb_language", "de-DE")
    check(tmdb._certification({"release_dates": {"results": [
        {"iso_3166_1": "US", "release_dates": [{"certification": "R"}]},
        {"iso_3166_1": "DE", "release_dates": [{"certification": ""}, {"certification": "16"}]}]}}) == "16", "de-DE -> DE 16")
    settings.put("tmdb_language", "en-US")
    check(tmdb._certification({}) is None, "missing -> None")

    print("new matches get categories at match time")
    add_item(6, "The Big Test Movie", 2019, None, None)
    with db.tx() as c:
        c.execute("UPDATE metadata SET cat_v=NULL, collection_id=NULL WHERE tmdb_id=1001")
    tmdb.queue_library(1)
    st = wait_meta(1)
    check(db.row("SELECT tmdb_id FROM items WHERE id=6")["tmdb_id"] == 1001, "matched")
    check(db.row("SELECT collection_id FROM metadata WHERE tmdb_id=1001")["collection_id"] == 9001, "collection on match")

    print("removed from TMDB -> stop asking")
    add_item(7, "Gone Movie", 2001, 4242, "manual")
    with db.tx() as c:
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,genres,fetched_at) VALUES('movie',4242,'Gone',2001,'[]',?)",
                  (int(time.time()),))
    tmdb._last_resume.clear()
    tmdb.resume_pending()
    wait_meta(1)
    check(tmdb.pending_count(1) == 0, "404 for a known id is stamped, not retried forever")

    print("filters")
    ids = lambda **kw: sorted(i["id"] for i in server.library_items(1, sort="title", u=U, **kw)["items"])  # noqa: E731
    check(ids(genres="Drama") == [1, 6], "genre filter")
    check(ids(genres="Drama|Science Fiction") == [1, 6], "two genres = movies with both")
    check(ids(genres="Drama|Thriller") == [], "AND across genres")
    check(ids(decade="2020") == [2, 3], "decade 2020s (uses the TMDB year)")
    check(ids(decade="1980") == [5], "decade 1980s")
    check(ids(collection=9001) == [1, 3, 6], "collection filter")
    order = [i["id"] for i in server.library_items(1, sort="poster", collection=9001, u=U)["items"]]
    check(order[-1] == 3, "collection in release order: %s" % order)
    check(ids(cert="G") == [3], "age rating filter")
    check(ids(genres="Drama", q="big") == [1, 6], "combines with search")
    check(ids(genres="Thriller", filter="nomatch") == [], "combines with Needs review / No match filters")
    r = server.library_items(1, sort="poster", genres="Drama", facets=1, u=U)
    check(r["total"] == 2 and "facets" in r, "total + facets returned")
    fg = {x["name"]: x["n"] for x in r["facets"]["genres"]}
    check(fg == {"Drama": 2, "Science Fiction": 2}, "facet counts follow the selection: %s" % fg)
    check({x["decade"] for x in server.library_genres(1, u=U)["decades"]} == {1980, 2000, 2010, 2020}, "decade facets")
    rs = server.library_items(1, sort="rating", u=U)["items"]
    rv = [i.get("rating") or 0 for i in rs]
    check(len(rs) == len(ids()) and rv == sorted(rv, reverse=True), "TMDB score sort: %s" % rv)

    print("collections view")
    cl = server.library_collections(1, u=U)
    check(len(cl["collections"]) == 1 and cl["collections"][0]["n"] == 3, "one collection with 3 movies")
    check(cl["collections"][0]["poster"] and cl["collections"][0]["year_from"] == 2019, "poster + years")
    check(server.library_collections(1, q="nothing", u=U)["collections"] == [], "collection search")

    print("item detail / home")
    d = server.item_detail(1, u=U)
    check(d["genres"] == ["Drama", "Science Fiction"] and d["collection"]["id"] == 9001, "detail: genres + collection")
    check(d["certification"] == "PG-13" and d["tags"] == [], "detail: rating + tags")
    h = server.home(u=U)
    rows = h["libraries"][0]["genre_rows"]
    check(rows and rows[0]["genre"] in ("Drama", "Science Fiction") and rows[0]["count"] == 2, "home genre rows: %s" %
          [(x["genre"], x["count"]) for x in rows])

    print("tags")
    server.apply_tags({"item_ids": [1, 2, 3], "add": ["Kids"]}, u=U)
    server.apply_tags({"item_ids": [2], "add": ["kids", "Weekend "]}, u=U)
    ts = {t["name"]: t["n"] for t in server.list_tags(u=U)}
    check(ts == {"Kids": 3, "Weekend": 1}, "case-insensitive tag names, counts: %s" % ts)
    kid = db.row("SELECT id FROM tags WHERE name='Kids'")["id"]
    check(ids(tag=kid) == [1, 2, 3] and ids(tag=kid, genres="Thriller") == [2], "tag filter combines with genres")
    server.apply_tags({"item_ids": [1], "remove": [kid]}, u=U)
    check(ids(tag=kid) == [2, 3], "remove a tag from one movie")
    wk = db.row("SELECT id FROM tags WHERE name='Weekend'")["id"]
    server.rename_tag(wk, {"name": "KIDS"}, u=U)
    check({t["name"]: t["n"] for t in server.list_tags(u=U)} == {"Kids": 2}, "rename onto an existing tag merges")
    with db.tx() as c:
        c.execute("DELETE FROM items WHERE id=3")
    check({t["name"]: t["n"] for t in server.list_tags(u=U)} == {"Kids": 1}, "deleted movie drops its tags")
    server.delete_tag(kid, u=U)
    check(server.list_tags(u=U) == [] and db.row("SELECT COUNT(*) n FROM item_tags")["n"] == 0, "delete tag")
    try:
        server.apply_tags({"item_ids": [], "add": ["x"]}, u=U)
        check(False, "empty selection rejected")
    except server.HTTPException:
        check(True, "empty selection rejected")
    check(server.library_items(1, sort="title", genres="Drama' OR 1=1 --", u=U)["items"] == [], "filters are parameterized")

    print("\n%d checks passed" % n_ok)


if __name__ == "__main__":
    main()
