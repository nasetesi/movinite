"""1.5.5: artwork to TV show folders (show / season posters, fanart, tvshow.nfo, episode thumbnails) and the
Poster Sounds settings tab.

    python3 tests/test_v155.py
"""
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9565
TMP = tempfile.mkdtemp(prefix="ms-v155-")
os.environ.update({"MS_DATA_DIR": TMP + "/data", "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY"})
import mock_tmdb  # noqa: E402
from app import artwork, db, tmdb  # noqa: E402

LIB = Path(TMP) / "tv"
fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def ep(path, show, season, episode):
    with db.tx() as c:
        return c.execute("INSERT INTO items(library_id,path,media_type,kind,title,sort_title,show,season,episode,size,mtime,"
                         "added_at) VALUES(1,?,'video','episode',?,?,?,?,?,1,1,1)",
                         (path, "E%d" % episode, "e", show, season, episode)).lastrowid


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    cols = {r["name"] for r in db.rows("PRAGMA table_info(libraries)")}
    check("art_thumbs" in cols, "libraries.art_thumbs column added by the migration")
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at,art_write,art_fanart,art_nfo,art_thumbs) "
                  "VALUES(1,'TV','tv',?,0,?,0,1,1,1)", (str(LIB), int(time.time())))
    e1 = ep(touch(LIB / "Test Show" / "Season 1" / "Test Show S01E01.mkv"), "Test Show", 1, 1)
    e2 = ep(touch(LIB / "Test Show" / "Season 1" / "Test Show S01E02.mkv"), "Test Show", 1, 2)
    e3 = ep(touch(LIB / "Test Show" / "Season 2" / "Test Show S02E01.mkv"), "Test Show", 2, 1)
    touch(LIB / "Test Show" / "Season 1" / "Test Show S01E02-thumb.jpg", b"MYTHUMB")        # user's own thumbnail
    ep(touch(LIB / "Loose Show S01E01.mkv"), "Loose Show", 1, 1)                           # in the library root
    ep(touch(LIB / "Mixed" / "Alpha S01E01.mkv"), "Alpha", 1, 1)                          # two shows in one folder
    ep(touch(LIB / "Mixed" / "Bravo S01E01.mkv"), "Bravo", 1, 1)
    ep(touch(LIB / "Unmatched" / "Unmatched S01E01.mkv"), "Unmatched", 1, 1)
    for show, tid in (("Test Show", 2001), ("Loose Show", 2001), ("Alpha", 2002), ("Bravo", 2002)):
        tmdb.fetch_details("tv", tid)
        tmdb.apply_show_match(1, show, tid, "matched")
    tmdb.match_show_seasons(1, "Test Show", 2001)

    print("dry run")
    lib, plan = artwork.plan_library(1)
    rel = lambda a: os.path.relpath(a["path"], LIB)  # noqa: E731
    ts = {(a["what"], a.get("season"), a.get("episode")): a for a in plan if a["item_id"] == "show:Test Show"}
    check(rel(ts[("poster", None, None)]) == "Test Show/poster.jpg" and ts[("poster", None, None)]["action"] == "create", "show poster.jpg in the show folder")
    check(rel(ts[("fanart", None, None)]) == "Test Show/fanart.jpg", "fanart.jpg")
    check(rel(ts[("nfo", None, None)]) == "Test Show/tvshow.nfo", "tvshow.nfo")
    check(rel(ts[("season", 1, None)]) == "Test Show/season01-poster.jpg" and rel(ts[("season", 2, None)]) == "Test Show/season02-poster.jpg", "season posters")
    check(rel(ts[("thumb", 1, 1)]) == "Test Show/Season 1/Test Show S01E01-thumb.jpg" and ts[("thumb", 1, 1)]["action"] == "create", "episode thumbnail next to the episode")
    check(ts[("thumb", 1, 2)]["action"] == "skip" and ts[("thumb", 1, 2)]["reason"] == "already there", "existing thumbnail kept")
    loose = [a for a in plan if a["item_id"] == "show:Loose Show"]
    check(any(a["what"] == "show" and a["action"] == "skip" for a in loose) and not any(a["what"] == "poster" for a in loose),
          "episodes in the library root: no show-level files")
    mixed = [a for a in plan if a["item_id"] in ("show:Alpha", "show:Bravo") and a["what"] == "poster"]
    check(not mixed, "folder with two shows: no show poster written into it")
    check(not any(a["item_id"] == "show:Unmatched" for a in plan), "unmatched shows are left alone")
    check(artwork.season_poster_name(0) == "season-specials-poster.jpg", "specials poster name")
    planned = sorted(a["path"] for a in plan if a["action"] != "skip")
    check(planned and not any(os.path.exists(p) for p in planned), "dry run wrote nothing (%d planned)" % len(planned))
    _, one = artwork.plan_library(1, [e1])
    check({a["item_id"] for a in one} == {"show:Test Show"}, "one show only (item ids of that show)")

    print("write")
    artwork.run_library(1)
    st = artwork.status[1]
    check(st["state"] == "done" and st["errors"] == 0, "run finished: %s" % {k: st.get(k) for k in ("written", "skipped", "errors", "error")})
    written = sorted(p for p in planned if os.path.exists(p))
    check(written == planned, "exactly the dry-run files were written (%d of %d)" % (len(written), len(planned)))
    check((LIB / "Test Show" / "poster.jpg").read_bytes()[:2] == b"\xff\xd8", "poster is a JPEG")
    check((LIB / "Test Show" / "season02-poster.jpg").is_file(), "season 2 poster written")
    check((LIB / "Test Show" / "Season 1" / "Test Show S01E02-thumb.jpg").read_bytes() == b"MYTHUMB", "user's thumbnail untouched")
    root = ET.fromstring((LIB / "Test Show" / "tvshow.nfo").read_bytes())
    check(root.tag == "tvshow" and root.findtext("title") == "Test Show" and root.find("uniqueid[@type='tmdb']").text == "2001", "tvshow.nfo: title + tmdb id")
    check([g.text for g in root.findall("genre")] == ["Comedy"] and root.findtext("premiered") == "2020-01-05", "tvshow.nfo: genres + premiered")
    posters = {r["poster"] for r in db.rows("SELECT poster, thumb FROM items WHERE show='Test Show'")}
    check(len(posters) == 1 and None not in posters, "episodes now use the folder poster (no rescan needed)")
    mtime = os.path.getmtime(LIB / "Test Show" / "poster.jpg")
    artwork.run_library(1)
    check(artwork.status[1]["written"] == 0 and os.path.getmtime(LIB / "Test Show" / "poster.jpg") == mtime, "second run writes nothing (never overwrites)")

    print("automatic for new show matches")
    called = []
    old, tmdb.on_matched = tmdb.on_matched, (lambda lid, ids: called.append((lid, sorted(ids))))
    with db.tx() as c:
        c.execute("DELETE FROM show_matches WHERE show='Test Show'")
    tmdb.process_library(1)
    tmdb.on_matched = old
    check(any(lid == 1 and set(ids) == {e1, e2, e3} for lid, ids in called), "a new show match calls the artwork hook with its episodes")

    print("UI (static)")
    app = (HERE.parent / "app" / "static" / "app.js").read_text()
    idx = (HERE.parent / "app" / "static" / "index.html").read_text()
    srv = (HERE.parent / "app" / "server.py").read_text()
    check('["sounds", "Poster Sounds"' in app, "Settings has a Poster Sounds tab")
    sounds = app.split('tab === "sounds"')[1].split('} else if (tab === "users")')[0]
    account = app.split('tab === "account"')[1].split('} else if (tab === "sounds")')[0]
    check(all(i in sounds for i in ("snd-on", "snd-hover", "snd-select", "snd-vol", "snd-test", "SFX.set(")), "all sound controls live in the new tab")
    check("snd-on" not in account and "#/settings/sounds" in account, "My account links to it instead")
    check('tab !== "account" && tab !== "sounds"' in app or '["sounds", "Poster Sounds", 0]' in app, "viewers can open it too")
    check("Poster sounds" in idx and "Interface sounds" not in idx, "top bar / account menu say Poster sounds")
    check('l.kind === "movies" || l.kind === "tv"' in app and 'id="showart"' in app and "aw-th" in app, "artwork button for TV libraries, on show pages, thumbnails option")
    check('"movies", "tv"' in srv and "art_thumbs" in srv and "_show_item_ids" in srv, "API: TV write, art_thumbs, one show")
    print("FAILS: %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
