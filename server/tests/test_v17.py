"""1.7: libraries grouped by share, one card per title (versions best-first), the same title on two shares shown
once in the views that span libraries, shared watch progress, offline fallback.

    python3 tests/test_v17.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-v17-")
os.environ["MS_DATA_DIR"] = TMP + "/data"
from app import auth, db, homerows, server, sharehealth, titles  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []
U = {"id": 1, "is_admin": 1}


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


NEXT = {"id": 100}


def add(lib, title, year, w, h, tmdb_id=None, bitrate=None, size=1, kind="movie", show=None, season=None, episode=None, added=None):
    NEXT["id"] += 1
    i = NEXT["id"]
    with db.tx() as c:
        c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,year,width,height,bitrate,size,mtime,added_at,"
                  "tmdb_id,meta_status,show,season,episode,vcodec,acodec,duration) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)",
                  (i, lib, "/srv/x/%d/%s.%d.mkv" % (lib, title, i), "video", kind, title, title.lower(), year, w, h, bitrate, size,
                   added or int(time.time()) - i, tmdb_id, "matched" if tmdb_id else None, show, season, episode,
                   "hevc", "eac3", 7200))
    return i


def state(lib_id, st):
    with sharehealth._lock:
        if st is None:
            sharehealth._state.pop(lib_id, None)
        else:
            sharehealth._state[lib_id] = {"state": st, "reason": "test", "ms": 5, "checked_at": time.time()}


def main():
    print("resolution rank and version order")
    check([titles.res_rank(*x) for x in [(3840, 2160), (3840, 1600), (2560, 1440), (2560, 1072), (1920, 1080), (1920, 800),
                                          (1280, 720), (720, 480), (None, None)]] == [4, 4, 3, 3, 2, 2, 1, 0, 0],
          "4K > 2K > 1080p > 720p > SD (scope films by width)")
    vs = [{"id": 1, "width": 1920, "height": 1080, "bitrate": 9e6}, {"id": 2, "width": 3840, "height": 2160, "bitrate": 20e6},
          {"id": 3, "width": 1280, "height": 720}, {"id": 4, "width": 3840, "height": 2160, "bitrate": 40e6},
          {"id": 5, "width": 1920, "height": 1080, "bitrate": 9e6, "size": 9}]
    check([v["id"] for v in sorted(vs, key=titles.version_sort_key)] == [4, 2, 5, 1, 3], "highest resolution, then bitrate, then size")

    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO shares(id,name,kind,remote,mount_point,created_at,allow_write) VALUES(1,'Movies','smb','//waimea/Media','',?,1)", (now,))
        c.execute("INSERT INTO shares(id,name,kind,remote,mount_point,created_at,allow_write) VALUES(2,'Sunset Movies','smb','//sunset/Media','',?,0)", (now,))
        for lid, name, kind, sid, so in [(2, "Sunset Movies", "movies", 2, 1), (1, "Waimea Movies", "movies", 1, 2), (3, "Waimea TV", "tv", 1, 3),
                                         (6, "Sunset TV", "tv", 2, 4), (7, "Kids Movies", "movies", None, 5), (5, "Music", "music", 2, 6)]:
            c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at,sort_order) VALUES(?,?,?,?,?,0,?,?)",
                      (lid, name, kind, "/srv/x/%d" % lid, sid, now, so))
    ids = {}
    for lib in (2, 1):          # the same films on both shares
        ids[(lib, "A4k")] = add(lib, "Alpha", 2001, 3840, 2160, 11, 30_000_000)
        ids[(lib, "A1080")] = add(lib, "Alpha", 2001, 1920, 1080, 11, 9_000_000)
        ids[(lib, "B")] = add(lib, "Bravo", 1999, 1920, 800, 12, 8_000_000)
        ids[(lib, "C4k")] = add(lib, "Clear And Present Danger", 1994, 3840, 2160, None, 20_000_000)
        ids[(lib, "C1080")] = add(lib, "Clear and Present Danger", 1994, 1920, 1080, None, 10_000_000)
        ids[(lib, "D4k_lo")] = add(lib, "Delta", 2025, 3840, 2160, 14, 15_000_000)
        ids[(lib, "D4k_hi")] = add(lib, "Delta", 2025, 3840, 1600, 14, 40_000_000)
        for e in (1, 2):
            ids[(lib + 10, e)] = add(3 if lib == 1 else 6, "Ep %d" % e, 2020, 1920, 1080, kind="episode", show="Night Shift", season=1, episode=e)
    ids["dupep"] = add(6, "Ep 1", 2020, 3840, 2160, kind="episode", show="Night Shift", season=1, episode=1)   # 2 files of S01E01
    ids["kids"] = add(7, "Echo", 2010, 1920, 1080, 15)
    with db.tx() as c:
        for t, n in [(11, "Alpha"), (12, "Bravo"), (14, "Delta"), (15, "Echo")]:
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,genres,fetched_at,release_date,rating,vote_count) VALUES('movie',?,?,2001,'[\"Drama\"]',?,'2001-01-01',7.5,900)", (t, n, now))
            c.execute("INSERT OR IGNORE INTO movie_genres(tmdb_id,genre) VALUES(?, 'Drama')", (t,))

    print("library grid: one card per film, the best version")
    r = server.library_items(2, sort="title", u=U)
    got = {i["title"].lower(): i for i in r["items"]}
    check(len(r["items"]) == 4 and r["total"] == 4, "4 films, not 7 files (%d / %s)" % (len(r["items"]), r["total"]))
    check(got["alpha"]["id"] == ids[(2, "A4k")] and got["alpha"]["versions"] == 2 and got["alpha"]["vres"] == ["4K", "1080p"],
          "Alpha: the 4K file is the card, versions 2 (4K, 1080p)")
    check(got["clear and present danger"]["id"] == ids[(2, "C4k")] and got["clear and present danger"]["versions"] == 2,
          "unmatched film: title + year (any case) groups its versions, 4K first")
    check(got["delta"]["id"] == ids[(2, "D4k_hi")], "two 4K files: the higher bitrate first")
    check("versions" not in got["bravo"], "single file: no versions field")
    check(len(server.library_items(2, sort="title", view="files", u=U)["items"]) == 7, "view=files still lists every file")

    print("show page: one row per episode")
    s = server.show_detail(6, "Night Shift", u=U)
    e1 = [e for e in s["seasons"][0]["episodes"] if e["episode"] == 1]
    check(len(e1) == 1 and e1[0]["id"] == ids["dupep"] and e1[0]["versions"] == 2, "S01E01 once, the 4K file first")

    print("details page: versions best first, copies, offline fallback")
    d = server.item_detail(ids[(1, "A1080")], u=U)
    check([v["id"] for v in d["versions"]] == [ids[(1, "A4k")], ids[(1, "A1080")]] and d["versions"][0]["res"] == "4K",
          "versions of this library, 4K first")
    check(d["copies"] == 1 and d["offline"] is False and d["fallback"] is None, "one copy elsewhere; share up -> no fallback")
    state(1, "offline")
    d = server.item_detail(ids[(1, "A1080")], u=U)
    check(d["offline"] and d["fallback"] == ids[(2, "A1080")] and d["fallback_library"] == "Sunset Movies",
          "Waimea offline: plays the same-resolution copy on Sunset")
    state(1, None)

    print("mirror groups")
    check(titles.mirror_groups("movies") == [[2, 1], [7]], "Sunset + Waimea movies mirror each other; Kids Movies stands alone (%s)" % titles.mirror_groups("movies"))
    check(titles.mirror_groups("tv") == [[3, 6]], "the two TV libraries mirror each other")

    print("home: one section per set of mirrored libraries")
    h = server.home(u=U)
    secs = [(L["library"]["id"], L["library"].get("mirrors")) for L in h["libraries"]]
    check(secs == [(2, ["Waimea Movies"]), (3, ["Sunset TV"]), (7, [])], "sections: %s" % secs)
    rec = next(R for R in h["libraries"][0]["smart_rows"] if R["key"] == "added")
    check(len(rec["items"]) == 4 and all(i["library_id"] == 2 for i in rec["items"]), "Recently added: each film once")
    check(next(i for i in rec["items"] if i["title"] == "Alpha")["id"] == ids[(2, "A4k")], "... as its 4K version")
    top = next(R for R in h["libraries"][0]["smart_rows"] if R["key"] == "top")
    check(next(i for i in top["items"] if i["title"] == "Alpha")["id"] == ids[(2, "A4k")], "Top movies picks the 4K file (was the first file)")
    gr = h["libraries"][0]["genre_rows"]
    check(gr and len(gr[0]["items"]) == 3 and gr[0]["count"] == 3, "genre rows: films, not files (3 matched films)")
    state(2, "offline")
    h = server.home(u=U)
    check([L["library"]["id"] for L in h["libraries"]][:1] == [1] and h["libraries"][0]["library"]["mirrors"] == ["Sunset Movies"],
          "Sunset offline: the Waimea section takes over")
    state(2, None)

    print("search: each title once")
    res = server.search("a", u=U)
    titles_ = [i["title"].lower() for i in res["items"]]
    check(len(titles_) == len(set(titles_)) and {"alpha", "bravo", "delta", "clear and present danger"} <= set(titles_),
          "films once each: %s" % titles_)
    check(next(i for i in res["items"] if i["title"] == "Alpha")["id"] == ids[(2, "A4k")], "from the first library, 4K version")
    check([s_["show"] for s_ in server.search("night", u=U)["shows"]] == ["Night Shift"], "a show on both shares once")
    ep = server.search("Ep 1", u=U)["episodes"]
    check(len(ep) == 1, "an episode once (%d)" % len(ep))
    state(2, "offline")
    check(next(i for i in server.search("alpha", u=U)["items"])["library_id"] == 1, "Sunset offline: the Waimea copy")
    check(server.search("night", u=U)["shows"][0]["library_id"] == 3, "... same for shows")
    state(2, None)

    print("watch progress is shared by every file of a title")
    server.save_progress(ids[(1, "A1080")], {"position": 600, "duration": 7200}, u=U)
    rows = {r["item_id"]: r["position"] for r in db.rows("SELECT item_id, position FROM progress WHERE user_id=1")}
    want = {ids[(lib, k)] for lib in (1, 2) for k in ("A4k", "A1080")}
    check(set(rows) == want and set(rows.values()) == {600}, "position saved on all 4 files of Alpha (both shares, both versions)")
    cw = server.home(u=U)["continue"]
    check(len(cw) == 1 and cw[0]["id"] == ids[(2, "A4k")] and cw[0]["position"] == 600, "Continue watching: once, best version on the first share")
    state(2, "offline")
    cw = server.home(u=U)["continue"]
    check(len(cw) == 1 and cw[0]["library_id"] == 1 and cw[0]["position"] == 600, "Sunset offline: resumes from the Waimea copy")
    state(2, None)
    server.set_watched(ids[(2, "B")], {"watched": True}, u=U)
    w = db.rows("SELECT item_id FROM progress WHERE user_id=1 AND watched=1")
    check({r["item_id"] for r in w} == {ids[(1, "B")], ids[(2, "B")]}, "Mark watched: both copies")
    ml = server.mylist(u=U)
    check([i["title"] for i in ml["watched"]] == ["Bravo"], "My List watched: once")
    d = server.item_detail(ids[(1, "B")], u=U)
    check(d["watched"], "the other copy shows as watched")
    server.save_progress(ids[(11, 1)], {"position": 100, "duration": 1500}, u=U)
    check(len(db.rows("SELECT 1 FROM progress WHERE user_id=1 AND position=100")) == 3, "episode progress: both shares + the 4K file")

    print("migration: existing progress copied to the other files (inserts only)")
    with db.tx() as c:
        c.execute("DELETE FROM progress")
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,?,1234,7200,0,5)", (ids[(1, "C1080")],))
        c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(1,?,99,7200,0,9)", (ids[(2, "C4k")],))
        c.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
    db.migrate()
    p = {r["item_id"]: r["position"] for r in db.rows("SELECT item_id, position FROM progress")}
    check(p[ids[(2, "C4k")]] == 99 and p[ids[(1, "C1080")]] == 1234, "existing rows unchanged")
    check(len(p) == 4 and p[ids[(1, "C4k")]] in (1234, 99), "missing copies filled in (%d rows)" % len(p))
    check(int(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"]) >= 7, "schema 7 or later")
    db.migrate()
    check(len(db.rows("SELECT 1 FROM progress")) == 4, "migrate is idempotent")

    print("share name (side menu heading) and grouped order")
    server.rename_share(1, {"name": "Waimea"}, u=U)
    s1 = db.row("SELECT name, allow_write, remote FROM shares WHERE id=1")
    check(s1["name"] == "Waimea" and s1["allow_write"] == 1 and s1["remote"] == "//waimea/Media", "rename: only the label changes")
    try:
        server.rename_share(1, {"name": "  "}, u=U)
        check(False, "empty name refused")
    except Exception:
        check(True, "empty name refused")
    libs = server.list_libraries(None)
    check([l["id"] for l in libs] == [2, 1, 3, 6, 7, 5] and libs[1]["share"]["name"] == "Waimea", "API order + share name for grouping")
    server.order_libraries({"ids": [2, 6, 5, 1, 3, 7]}, u=U)
    check([l["id"] for l in server.list_libraries(None)] == [2, 6, 5, 1, 3, 7], "group-by-group order saves")

    print("pins follow the film")
    with db.tx() as c:
        c.execute("INSERT INTO home_pins(row,item_id,mode,created_at) VALUES('top',?,-1,1)", (ids[(2, "A1080")],))
    top = [i for i, _ in homerows.top_movies(2)]
    check(ids[(2, "A4k")] not in top and ids[(2, "A1080")] not in top, "hiding the 1080p file hides the film (4K card too)")

    print("web app")
    js = (HERE.parent / "app/static/app.js").read_text()
    css = (HERE.parent / "app/static/style.css").read_text()
    check("function libGroups(" in js and 'class="navgrp"' in js and "navgrp-h" in js, "side menu grouped by share")
    check("groupHealthLib(g)" in js and "libDotInGroup(" in js, "status dot on the share heading (library dot only when different)")
    check('data-gup="' in js and "data-renshare" in js and "/api/shares/${s.id}/name" in js, "settings: move a share's group, rename its heading")
    check("src.dataset.grp !== tr.dataset.grp" in js, "drag and drop stays inside a group")
    check("function resBadge(" in js and ".rbadge" in css, "resolution badge on posters")
    check('id="ver-sel"' in js and "function pickVersion(" in js and "playItem(id, 0, { exact" in js, "version picker + version choice")
    check("it.offline && it.fallback" in js, "offline share: plays the online copy")
    check('"4K" : w >= 2400 || h >= 1300 ? "2K"' in js, "2K in resName")
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7), "version is 1.7 or later")


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
