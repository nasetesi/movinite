"""1.3 artwork-to-folders: naming, no-overwrite, in-place overwrite, read-only failures, dry run, .nfo validity.

    python3 tests/test_artwork.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PORT = 9561
TMP = tempfile.mkdtemp(prefix="ms-art-test-")
os.environ.update({"MS_DATA_DIR": TMP + "/data", "MS_TMDB_API_BASE": "http://127.0.0.1:%d/3" % PORT,
                   "MS_TMDB_IMAGE_BASE": "http://127.0.0.1:%d/t/p" % PORT, "MS_TMDB_KEY": "GOODKEY"})
import mock_tmdb  # noqa: E402
from app import artwork, db, tmdb  # noqa: E402

LIB = Path(TMP) / "lib"
n_ok = 0


def check(cond, msg):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1
    print("  ok -", msg)


def touch(p, data=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def add_item(path, title, year, tmdb_id, status="matched"):
    with db.tx() as c:
        cur = c.execute("INSERT INTO items(library_id,path,media_type,kind,title,sort_title,year,size,mtime,added_at,"
                        "tmdb_id,meta_status) VALUES(1,?,'video','movie',?,?,?,1,1,1,?,?)",
                        (path, title, title.lower(), year, tmdb_id, status))
        return cur.lastrowid


def add_meta(tid, title, year, poster="/p%d.jpg", backdrop="/b%d.jpg"):
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO metadata(kind,tmdb_id,title,original_title,year,overview,tagline,genres,rating,"
                  "vote_count,runtime,poster,backdrop,fetched_at,release_date,imdb_id,poster_path,backdrop_path,extra) "
                  "VALUES('movie',?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?,?,?)",
                  (tid, title, title, year, "Plot with <tags> & \"quotes\".", "Tag", json.dumps(["Drama", "Action"]), 7.3,
                   100, 120, int(time.time()), "%d-05-01" % year, "tt%07d" % tid,
                   (poster % tid) if poster else None, (backdrop % tid) if backdrop else None,
                   json.dumps({"studios": ["Studio & Co"], "countries": ["US"], "collection": "Coll", "original_language": "en"})))


def main():
    mock_tmdb.serve(PORT)
    db.migrate()
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at,art_write,art_fanart,art_nfo) "
                  "VALUES(1,'Movies','movies',?,0,?,1,1,1)", (str(LIB), int(time.time())))
    A = add_item(touch(LIB / "Alpha (2001)" / "Alpha (2001).mkv"), "Alpha", 2001, 101)
    B = add_item(touch(LIB / "Bravo (2002)" / "Bravo (2002).mkv"), "Bravo", 2002, 102)
    touch(LIB / "Bravo (2002)" / "folder.jpg", b"MINE")                      # existing artwork, other name
    C = add_item(touch(LIB / "Charlie (2003)" / "Charlie (2003).mkv"), "Charlie", 2003, 103)
    touch(LIB / "Charlie (2003)" / "poster.jpg", b"OLDPOSTER")              # existing, same name
    touch(LIB / "Charlie (2003)" / "Charlie (2003).nfo", b"<movie/>")         # existing nfo, other name
    X = add_item(touch(LIB / "Loose" / "Xray (2004).mkv"), "Xray", 2004, 104)
    Y = add_item(touch(LIB / "Loose" / "Yankee (2005).mkv"), "Yankee", 2005, 105)
    Z = add_item(touch(LIB / "Zulu (2006).mkv"), "Zulu", 2006, 106)           # in the library root
    D1 = add_item(touch(LIB / "Delta (2007)" / "Delta (2007) cd1.mkv"), "Delta", 2007, 107)
    D2 = add_item(touch(LIB / "Delta (2007)" / "Delta (2007) cd2.mkv"), "Delta", 2007, 107)
    S1 = add_item(touch(LIB / "Pair" / "Sierra (2012).mkv"), "Sierra", 2012, 111)     # two different files that
    add_item(touch(LIB / "Pair" / "Tango (2013).mkv"), "Tango", 2013, 111)             # were matched to one TMDB id
    E = add_item(touch(LIB / "Action" / "Echo (2008).mkv"), "Echo", 2008, 108)  # folder also has sub-folders
    F = add_item(touch(LIB / "Action" / "Foxtrot (2009)" / "Foxtrot (2009).mkv"), "Foxtrot", 2009, 109)
    G = add_item(touch(LIB / "Golf (2010)" / "Golf (2010).mkv"), "Golf", 2010, 110, status="nomatch")
    add_item(touch(LIB / "Hotel (2011)" / "Hotel (2011).mkv"), "Hotel", 2011, None, status="nomatch")
    for tid, t, y in [(101, "Alpha & <Omega>", 2001), (102, "Bravo", 2002), (103, "Charlie", 2003), (104, "Xray", 2004),
                      (105, "Yankee", 2005), (106, "Zulu", 2006), (107, "Delta", 2007), (108, "Echo", 2008),
                      (109, "Foxtrot", 2009), (110, "Golf", 2010), (111, "Sierra", 2012)]:
        add_meta(tid, t, y)
    add_meta(105, "Yankee", 2005, backdrop=None)

    print("dry run")
    lib, plan = artwork.plan_library(1)
    by = {(a["item_id"], a["what"]): a for a in plan}
    rel = lambda a: os.path.relpath(a["path"], LIB)  # noqa: E731
    check(rel(by[(A, "poster")]) == "Alpha (2001)/poster.jpg" and by[(A, "poster")]["action"] == "create", "single-movie folder -> poster.jpg")
    check(rel(by[(A, "fanart")]) == "Alpha (2001)/fanart.jpg", "fanart.jpg")
    check(rel(by[(A, "nfo")]) == "Alpha (2001)/movie.nfo", "movie.nfo")
    check(by[(B, "poster")]["action"] == "skip" and "folder.jpg" in by[(B, "poster")]["reason"], "existing folder.jpg -> poster skipped")
    check(by[(C, "poster")]["action"] == "skip" and by[(C, "poster")]["reason"] == "already there", "existing poster.jpg kept (no overwrite)")
    check(by[(C, "nfo")]["action"] == "skip", "existing <name>.nfo counts as an nfo")
    check(rel(by[(X, "poster")]) == "Loose/Xray (2004)-poster.jpg" and rel(by[(X, "nfo")]) == "Loose/Xray (2004).nfo",
          "two movies in one folder -> <filename>-poster.jpg / <filename>.nfo")
    check(by[(Y, "fanart")]["action"] == "skip", "no TMDB backdrop -> fanart skipped")
    check(rel(by[(Z, "poster")]) == "Zulu (2006)-poster.jpg", "file in the library root -> prefixed names")
    check(rel(by[(D1, "poster")]) == "Delta (2007)/poster.jpg", "cd1/cd2 of the same movie still count as one movie")
    check(rel(by[(S1, "poster")]) == "Pair/Sierra (2012)-poster.jpg", "different movies on one TMDB id still count as two")
    check(rel(by[(E, "poster")]) == "Action/Echo (2008)-poster.jpg", "folder with movie sub-folders -> prefixed names")
    check(rel(by[(F, "poster")]) == "Action/Foxtrot (2009)/poster.jpg", "nested single-movie folder -> poster.jpg")
    check(not any(a["item_id"] == G for a in plan), "unmatched movies are left alone")
    planned = sorted(a["path"] for a in plan if a["action"] != "skip")
    check(not any(os.path.exists(p) for p in planned), "dry run wrote nothing")

    print("write")
    artwork.run_library(1)
    st = artwork.status[1]
    check(st["state"] == "done" and st["errors"] == 0, "run finished: %s" % {k: st.get(k) for k in ("written", "skipped", "errors")})
    written = sorted(p for p in planned if os.path.exists(p))
    check(written == planned, "exactly the dry-run files were written (%d)" % len(written))
    check((LIB / "Bravo (2002)" / "folder.jpg").read_bytes() == b"MINE", "existing folder.jpg untouched")
    check((LIB / "Charlie (2003)" / "poster.jpg").read_bytes() == b"OLDPOSTER", "existing poster.jpg untouched")
    check((LIB / "Alpha (2001)" / "poster.jpg").read_bytes()[:2] == b"\xff\xd8", "poster is a JPEG")
    mode = stat.S_IMODE(os.stat(LIB / "Alpha (2001)" / "poster.jpg").st_mode)
    check(mode & 0o644 == 0o644 and not mode & 0o022, "new files are 0644 (%o)" % mode)
    check(not list(LIB.rglob("*.part")) and not list(LIB.rglob(".media-server-write-test*")), "no temp files left")

    print(".nfo")
    nfo = (LIB / "Alpha (2001)" / "movie.nfo").read_bytes()
    root = ET.fromstring(nfo)
    check(root.tag == "movie" and root.findtext("title") == "Alpha & <Omega>", "well-formed XML, escaped title")
    check(root.find("uniqueid[@type='tmdb']").text == "101" and root.find("uniqueid[@type='tmdb']").get("default") == "true", "tmdb uniqueid")
    check(root.find("uniqueid[@type='imdb']").text == "tt0000101", "imdb uniqueid")
    check(root.findtext("year") == "2001" and root.findtext("premiered") == "2001-05-01", "year / premiered")
    check([g.text for g in root.findall("genre")] == ["Drama", "Action"], "genres")
    check(root.find("ratings/rating[@name='themoviedb']/value").text == "7.3", "rating")
    check(root.findtext("set/name") == "Coll" and root.findtext("studio") == "Studio & Co", "collection / studio")
    check(nfo.startswith(b'<?xml version="1.0" encoding="UTF-8"'), "XML declaration")
    try:
        r = subprocess.run(["xmllint", "--noout", "-"], input=nfo, capture_output=True)
        check(r.returncode == 0, "xmllint accepts it")
    except FileNotFoundError:
        pass

    print("second run: nothing to do")
    artwork.run_library(1)
    check(artwork.status[1]["written"] == 0, "idempotent (0 written, %d skipped)" % artwork.status[1]["skipped"])

    print("overwrite in place")
    p = LIB / "Charlie (2003)" / "poster.jpg"
    ino = os.stat(p).st_ino
    with db.tx() as c:
        c.execute("UPDATE libraries SET art_overwrite=1")
    _, plan2 = artwork.plan_library(1)
    ow = [a for a in plan2 if a["action"] == "overwrite"]
    check(any(a["path"] == str(p) for a in ow), "overwrite plans poster.jpg")
    check(not any(a["path"].endswith("folder.jpg") for a in plan2 if a["action"] != "skip"), "other names never overwritten")
    artwork.run_library(1, [C])
    check(p.read_bytes()[:2] == b"\xff\xd8" and os.stat(p).st_ino == ino, "rewritten in place (same inode -> owner kept)")
    check((LIB / "Charlie (2003)" / "Charlie (2003).nfo").read_bytes() == b"<movie/>", "existing <name>.nfo kept (not our name)")
    with db.tx() as c:
        c.execute("UPDATE libraries SET art_overwrite=0")

    print("permission denied -> clear message, stops")
    os.remove(LIB / "Alpha (2001)" / "poster.jpg")
    for d in [LIB] + [x for x in LIB.rglob("*") if x.is_dir()]:
        os.chmod(d, 0o555)
    try:
        ok, msg = artwork.check_writable(db.row("SELECT * FROM libraries WHERE id=1"))
        check(not ok and "permission denied" in msg, "check_writable: %s" % msg[:70])
        artwork.run_library(1)
        st = artwork.status[1]
        check(st["state"] == "error" and "permission" in st["error"], "run stops with: %s" % st["error"][:70])
    finally:
        for d in [LIB] + [x for x in LIB.rglob("*") if x.is_dir()]:
            os.chmod(d, 0o755)

    print("read-only mount (EROFS)")
    ro = Path(TMP) / "ro"
    ro.mkdir()
    r = subprocess.run(["sudo", "-n", "mount", "--bind", "-o", "ro", str(LIB), str(ro)], capture_output=True)
    if r.returncode == 0:
        try:
            subprocess.run(["sudo", "-n", "mount", "-o", "remount,bind,ro", str(ro)], capture_output=True)
            with db.tx() as c:
                c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at,art_write) "
                          "VALUES(2,'RO','movies',?,NULL,0,?,1)", (str(ro), int(time.time())))
                c.execute("UPDATE items SET library_id=2, path=replace(path, ?, ?) WHERE id=?", (str(LIB), str(ro), A))
            ok, msg = artwork.check_writable(db.row("SELECT * FROM libraries WHERE id=2"))
            check(not ok and "read-only" in msg, "read-only mount detected: %s" % msg[:80])
            artwork.run_library(2)
            check(artwork.status[2]["state"] == "error" and "read-only" in artwork.status[2]["error"], "run refuses cleanly")
            check(not (LIB / "Alpha (2001)" / "poster.jpg").exists(), "nothing written")
        finally:
            subprocess.run(["sudo", "-n", "umount", str(ro)], capture_output=True)
    else:
        print("  (skipped: no sudo for a read-only bind mount)")

    print("automatic writing after a match")
    with db.tx() as c:
        c.execute("UPDATE items SET library_id=1, path=replace(path, ?, ?) WHERE id=?", (str(ro), str(LIB), A))
        c.execute("UPDATE items SET tmdb_id=110, meta_status='matched' WHERE id=?", (G,))
    artwork.status.pop(1, None)      # forget the deliberate permission error above (auto-writing backs off 10 min after one)
    tmdb._after_match(1, [G])
    t0 = time.time()
    while time.time() - t0 < 20 and not (LIB / "Golf (2010)" / "poster.jpg").exists():
        time.sleep(0.2)
    check((LIB / "Golf (2010)" / "poster.jpg").exists(), "new match -> poster written automatically")
    with db.tx() as c:
        c.execute("UPDATE libraries SET art_write=0")
        c.execute("UPDATE items SET meta_status='matched', tmdb_id=101 WHERE title='Hotel'")
    hid = db.row("SELECT id FROM items WHERE title='Hotel'")["id"]
    tmdb._after_match(1, [hid])
    time.sleep(4)
    check(not (LIB / "Hotel (2011)" / "poster.jpg").exists(), "option off -> nothing written automatically")
    print("\nALL %d ARTWORK CHECKS PASSED" % n_ok)
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
