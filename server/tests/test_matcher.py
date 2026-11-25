"""1.3 title matcher with a fake TMDB search (no network): editions, year preference, wrong-year review,
shorter-title retries, sequels, typos, and manual matches never overridden.

    python3 tests/test_matcher.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MS_DATA_DIR"] = tempfile.mkdtemp(prefix="ms-match-test-")
from app import db, media, tmdb  # noqa: E402

CAT = [  # id, title, release date, popularity
    (1, "Salt", "2010-07-21", 30), (2, "Sin City", "2005-04-01", 40), (3, "Rango", "2011-03-02", 30),
    (4, "Rango", "2003-01-01", 0.5), (5, "Star Wars", "1977-05-25", 80), (6, "The Dark Knight", "2008-07-16", 90),
    (7, "Die Hard: With a Vengeance", "1995-05-19", 40), (8, "Die Harder", "1990-07-02", 2), (9, "Die Hard", "1988-07-15", 50),
    (10, "Die Hard 2", "1990-07-02", 40), (11, "Iron Man 3", "2013-04-18", 60), (12, "F1", "2025-06-25", 70),
    (13, "Anchorman 2: The Legend Continues", "2013-12-18", 30), (14, "The Matrix", "1999-03-30", 80),
    (15, "Pokemon: The First Movie", "1998-07-18", 20), (16, "Gladiator", "2000-05-01", 70), (17, "Gladiator", "1992-03-06", 3),
    (18, "Hamilton", "2020-07-03", 30), (19, "Hamilton", "1998-01-01", 1), (20, "Sweeney Todd: The Demon Barber of Fleet Street", "2007-12-21", 40),
    (21, "Mission: Impossible - Fallout", "2018-07-13", 50), (22, "Interstellar", "2014-11-05", 90),
    (26, "Motor City", "2026-07-23", 21), (27, "Motor City Waves", "2025-03-08", 0.3), (28, "Eden", "2025-04-03", 5.1),
    (29, "Eden", "2024-06-08", 0.25), (30, "Vacation", "2015-07-28", 6.8), (31, "National Lampoon's Vacation", "1983-07-28", 7),
    (23, "Dinosaur", "2000-05-19", 30), (24, "Dinosaur Adventure", "2000-01-01", 1), (25, "The Cable Guy", "1996-06-14", 30),
]


OTHER_RELEASES = {(28, 2024)}   # TMDB's year filter also matches festival / re-release dates


def norm(s):
    return set(tmdb._toks(s))


def hit(q, t):
    """like TMDB: every word must be in the title, the last one may be a prefix"""
    qw, tw = tmdb._toks(q), set(tmdb._toks(t))
    return bool(qw) and set(qw[:-1]) <= tw and any(w.startswith(qw[-1]) for w in tw)


def searcher(q, year):
    out = [{"id": i, "title": t, "original_title": t, "release_date": d, "popularity": p}
           for i, t, d, p in CAT if hit(q, t) and (not year or d.startswith(str(year)) or (i, year) in OTHER_RELEASES)]
    return sorted(out, key=lambda r: -r["popularity"])


n_ok = 0


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def match(fname):
    p = media.parse_movie(Path("/m") / fname)
    r = tmdb.match_movie(p["title"], p["year"], searcher)
    return p, r


def got(fname, tid, status="matched"):
    p, r = match(fname)
    rid = r["result"]["id"] if r["result"] else r["candidate"]
    check(r["status"] == status and rid == tid, "%-48s -> %s %s (%s%s)" % (
        fname, r["status"], rid, r["confidence"], ", " + r["note"] if r["note"] else ""))
    return p, r


def main():
    print("editions")
    p, _ = got("Salt.2010.DIRECTORS.CUT.1080p.mkv", 1)
    check(p["title"] == "Salt" and p["edition"] == "Director's Cut", "edition split off: %r" % p["edition"])
    p, _ = got("Sin City (2005) EXTENDED and UNRATED.mkv", 2)
    check("Extended" in p["edition"] and "Unrated" in p["edition"], "two editions: %r" % p["edition"])
    print("year preference / wrong year")
    got("Rango (2011).mkv", 3)
    got("Gladiator (2000).mkv", 16)
    got("Hamilton (2020).mkv", 18)
    _, r = got("The Dark Knight (2026).mkv", 6, "review")
    check("2008" in r["note"], "review note names the TMDB year: %s" % r["note"])
    print("popularity breaks near-ties")
    got("Motor City (2025).mkv", 26)
    got("Eden (2024).mkv", 28)
    _, r = got("Vacation (1983).mkv", 31)
    check(r["confidence"] < tmdb.REVIEW_BELOW and r["candidate"] == 30, "partial match is flagged, same-title film offered: %s" % r["note"])
    _, r = got("Rango (2009).mkv", 3, "review")
    print("shorter titles")
    got("F1 The Movie (2025).mkv", 12)
    got("Star Wars Episode IV - A New Hope (1977).mkv", 5)
    got("Mission Impossible - Fallout (2018).mkv", 21)
    print("sequels")
    got("Iron Man Three (2013).mkv", 11)
    got("Die Hard 3 (1995).mkv", 7)
    got("Anchorman 2 (2013).mkv", 13)
    print("typos")
    got("Interstelar (2014).mkv", 22)
    got("Dinosour (2000).mkv", 23)
    got("The Cable Gyu (1996).mkv", 25)
    got("The Matrx (1999).mkv", 14)
    print("no year in the file name")
    got("Interstellar.mkv", 22)
    print("nothing")
    _, r = match("Qwxzy Plorp (2001).mkv")
    check(r["status"] == "nomatch", "unknown title -> nomatch")

    print("manual matches are never overridden")
    db.migrate()
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'M','movies','/x',0,?)", (int(time.time()),))
        for i, (st, tid) in enumerate([("manual", 22), ("matched", 3), (None, None)], 1):
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,size,mtime,added_at,tmdb_id,meta_status)"
                      " VALUES(?,1,?,'video','movie','Rango','rango',2011,1,1,1,?,?)", (i, "/x/%d.mkv" % i, tid, st))
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,fetched_at) VALUES('movie',22,'Interstellar',2014,?)", (int(time.time()),))
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,fetched_at) VALUES('movie',3,'Rango',2011,?)", (int(time.time()),))
    calls, fetched = [], []
    real = (tmdb.match_movie, tmdb.fetch_details, tmdb.settings.tmdb_enabled)
    tmdb.match_movie = lambda t, y, searcher=None: calls.append((t, y)) or {"status": "nomatch", "result": None,
                                                                         "confidence": 0, "candidate": None, "note": None}
    tmdb.fetch_details = lambda kind, tid, force=False: fetched.append(tid)
    tmdb.settings.tmdb_enabled = lambda: True
    try:
        for force in (False, True):
            calls.clear(); fetched.clear()
            tmdb.process_library(1, force=force)
            check(len(calls) == 1, "force=%s: only the unmatched item is searched (%d)" % (force, len(calls)))
            check(db.row("SELECT meta_status, tmdb_id FROM items WHERE id=1") == {"meta_status": "manual", "tmdb_id": 22}
                  if isinstance(db.row("SELECT 1 AS x"), dict) else tuple(db.row("SELECT meta_status, tmdb_id FROM items WHERE id=1")) == ("manual", 22),
                  "force=%s: manual match untouched" % force)
            if force:
                check(22 in fetched, "refresh-all only re-downloads the manual match's details")
            with db.tx() as c:
                c.execute("UPDATE items SET meta_status=NULL, tmdb_id=NULL WHERE id=3")
    finally:
        tmdb.match_movie, tmdb.fetch_details, tmdb.settings.tmdb_enabled = real
    tmdb.apply_movie_match([1], 22, "manual")
    row = db.row("SELECT * FROM items WHERE id=1")
    check(row["meta_status"] == "manual" and row["meta_confidence"] == 1 and row["sort_title"].startswith("interstellar"),
          "manual match keeps confidence 1 and sorts by the TMDB title (%r)" % row["sort_title"])
    print("\nALL %d MATCHER CHECKS PASSED" % n_ok)


if __name__ == "__main__":
    main()
