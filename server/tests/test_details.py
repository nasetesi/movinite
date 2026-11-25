"""1.4.3: movie details page -- credits stored from the details request, the backfill, actor photos (lazy, cached),
similar movies (TMDB recommendations -> collection -> genres) and an actor's movies.

    python3 tests/test_details.py
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
PORT = 9563
TMP = tempfile.mkdtemp(prefix="ms-details-test-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY",
                   "MS_TMDB_MAX_RPS": "20"})

import mock_tmdb  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from app import config, db, server, tmdb  # noqa: E402

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
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] == "6", "schema 6")
    now = int(time.time())
    # library: 1001/1002/1003 real mock movies + synthetic 5001.. with genres / collection for the similar list
    films = [(1, 1001, "The Big Test Movie"), (2, 1002, "Another Film"), (3, 1003, "Remux Test")]
    extra = [(4, 5004, "Saga Two", ["Drama", "Science Fiction"], 9001), (5, 5005, "Genre Twin", ["Drama", "Science Fiction"], None),
             (6, 5006, "Half Match", ["Drama"], None), (7, 5007, "Other Thing", ["Horror"], None),
             (8, 5008, "Recommends Big", ["Comedy"], None)]
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies','/m',0,?)", (now,))
        c.execute("INSERT INTO users(id,username,pw_hash,is_admin,created_at) VALUES(1,'a','x',1,0)")
        for i, t, title in films:
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,size,mtime) "
                      "VALUES(?,1,?,'video','movie',?,?,2019,?,?,'matched',1,1)", (i, "/m/%d.mkv" % i, title, title.lower(), now, t))
        for i, t, title, g, col in extra:
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,size,mtime) "
                      "VALUES(?,1,?,'video','movie',?,?,2010,?,?,'matched',1,1)", (i, "/m/%d.mkv" % i, title, title.lower(), now, t))
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,genres,rating,vote_count,fetched_at,collection_id,collection_name,cat_v) "
                      "VALUES('movie',?,?,2010,?,7,1000,?,?,?,3)", (t, title, json.dumps(g), now, col, "Test Pattern Collection" if col else None))
            for x in g:
                c.execute("INSERT INTO movie_genres VALUES(?,?)", (t, x))
        c.execute("INSERT INTO movie_recs VALUES(5008, 1001, 0)")       # someone else's recs point at Big Test Movie
        # a second copy of Genre Twin (another edition) must not be listed twice
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,added_at,tmdb_id,meta_status,size,mtime) "
                  "VALUES(9,1,'/m/9.mkv','video','movie','Genre Twin','genre twin',2010,?,5005,'matched',1,1)", (now,))

    print("backfill")
    pend0 = tmdb.pending_count(1)
    check(pend0 >= 3, "matched movies without 1.4.3 credits count as pending (%d)" % pend0)
    d0 = server.item_detail(1, u=U)
    check(d0["cast"] == [] and d0["credits_pending"] is True, "page works without cast while the backfill runs")
    check(isinstance(d0["similar"], list), "similar list present before backfill")
    tmdb.queue_library(1)
    for _ in range(100):
        if tmdb.pending_count(1) == 0 and (tmdb.status.get(1) or {}).get("state") in ("done", None):
            break
        time.sleep(0.2)
    check(tmdb.pending_count(1) == 0, "backfill finished, nothing pending")
    st = tmdb.status.get(1) or {}
    check(st.get("phase") == "categories", "pill phase is the details pass (%s)" % st.get("phase"))
    check(db.row("SELECT meta_status, tmdb_id FROM items WHERE id=1")["tmdb_id"] == 1001, "match kept")

    print("credits")
    d = server.item_detail(1, u=U)
    check(len(d["cast"]) == 8 and d["cast"][0]["character"] == "Character 1", "top-billed cast in order (%d)" % len(d["cast"]))
    check(all(p["name"] for p in d["cast"]) and d["credits_pending"] is False, "names, not pending any more")
    check(sum(1 for p in d["cast"] if not p["has_photo"]) == 1, "an actor without a TMDB photo is flagged")
    check(len(d["directors"]) == 1 and d["writers"] == [], "director kept, key grip dropped")
    check(db.row("SELECT COUNT(*) n FROM movie_crew WHERE job NOT IN ('director','writer')")["n"] == 0, "only directors / writers stored")
    # refetch replaces, does not duplicate
    tmdb.fetch_details("movie", 1001, force=True)
    check(db.row("SELECT COUNT(*) n FROM movie_cast WHERE tmdb_id=1001")["n"] == 8, "refetch replaces the cast")

    print("photos (lazy, cached)")
    pid = d["cast"][0]["id"]
    check(db.row("SELECT photo FROM people WHERE id=?", (pid,))["photo"] is None, "no photo downloaded before anyone looks")
    imgs0 = mock_tmdb.stats["images"]
    r = server.person_photo(pid, u=U)
    check(r.status_code == 200 and Path(r.path).is_file(), "photo served")
    server.person_photo(pid, u=U)
    check(mock_tmdb.stats["images"] - imgs0 == 1, "downloaded once, then cached")
    nophoto = [p for p in d["cast"] if not p["has_photo"]][0]["id"]
    try:
        server.person_photo(nophoto, u=U); check(False, "404")
    except HTTPException as e:
        check(e.status_code == 404, "no photo -> 404 (initials shown)")

    print("similar movies")
    sim = server.item_detail(1, u=U)["similar"]
    ids = [x["id"] for x in sim]
    check(1 not in ids, "never the movie itself")
    check(ids.index(8) < ids.index(4), "TMDB recommendations first (incl. reverse): %s" % ids)
    check(ids.index(4) < ids.index(5), "then the same collection")
    check(5 in ids and ids.index(5) < ids.index(6), "then most shared genres")
    check(ids.count(5) + ids.count(9) == 1, "one entry per TMDB movie")
    check(7 not in ids, "no shared genre, no recommendation -> not listed")
    check({x["reason"] for x in sim} >= {"TMDB recommends", "Similar genres"}, "reasons: %s" % sorted({x["reason"] for x in sim}))
    check(all("poster" in x for x in sim), "card fields present")

    print("actor page")
    both = db.row("SELECT a.person_id p FROM movie_cast a JOIN movie_cast b ON a.person_id=b.person_id "
                  "WHERE a.tmdb_id=1001 AND b.tmdb_id=1002")
    check(both is not None, "an actor appears in two mock movies")
    pd = server.person_detail(both["p"], library_id=1, u=U)
    check(sorted(x["id"] for x in pd["items"]) == [1, 2], "actor page lists the movies in your library: %s" % [x["title"] for x in pd["items"]])
    check(all(x["reason"].startswith("as ") for x in pd["items"]), "with the character")
    dr = db.row("SELECT person_id FROM movie_crew WHERE tmdb_id=1001 AND job='director'")["person_id"]
    check(any("Director" in x["reason"] for x in server.person_detail(dr, library_id=1, u=U)["items"]), "director page")
    check(server.person_detail(both["p"], library_id=99, u=U)["items"] == [], "other library -> empty")
    try:
        server.person_detail(123, u=U); check(False, "404")
    except HTTPException as e:
        check(e.status_code == 404, "unknown person -> 404")

    print("non-movie items unchanged")
    with db.tx() as c:
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,meta_status,size,mtime) "
                  "VALUES(20,1,'/m/home.mkv','video','movie','Home Video','home video',?,'nomatch',1,1)", (now,))
    h = server.item_detail(20, u=U)
    check(h["cast"] == [] and h["credits_pending"] is False and isinstance(h["similar"], list), "unmatched movie: no cast, no error")
    print("\n%d checks passed" % n_ok)


main()
