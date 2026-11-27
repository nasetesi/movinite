"""2.5: watch progress for shared (remote) titles appears in Continue Watching.

    python3 tests/test_v25.py

Made-up logins only. Nothing leaves 127.0.0.1.
"""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="ms-v25-")
DATA = TMP + "/data"
os.environ["MS_DATA_DIR"] = DATA
os.environ["MS_SESSION_DAYS"] = "30"

from app import auth, db, fed, keys, server, settings  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
db_src = (ROOT / "app/db.py").read_text()
fed_src = (ROOT / "app/fed.py").read_text()
srv_src = (ROOT / "app/server.py").read_text()

print("version and docs")
check(__version__ == "2.5", "version is 2.5 (%s)" % __version__)
check("SCHEMA_VERSION = 15" in db_src, "SCHEMA_VERSION is 15")
check("_backup_db(c, 15)" in db_src, "migrate snapshots pre-schema15 before the bump")
check("CREATE TABLE IF NOT EXISTS remote_progress" in db_src, "schema 15 has remote_progress")
check("chmod(0o600)" in db_src and "pre-schema%d" in db_src, "schema backups are written mode 600")
check("## 2.5" in ch and ch.find("## 2.5") < ch.find("## 2.4.4"), "CHANGELOG has 2.5 above 2.4.4")
check("schema 15" in ch.lower() or "Schema 15" in ch, "changelog mentions schema 15")
check("Continue watching" in ch and ("shared" in ch.lower() or "remote" in ch.lower()),
      "changelog mentions shared titles in Continue watching")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
check("tukuia.com" not in rd and "Waimea" not in rd and "Sunset" not in rd,
      "README does not use private host or share names")
check("remote_progress" in fed_src and "def continue_items" in fed_src, "fed helpers for shared progress exist")
check("item_id < 0" in srv_src and "save_remote_progress" in srv_src, "save_progress writes remote_progress for shared ids")
check("_merge_continue" in srv_src, "Continue watching merges local and shared titles")
check("it.unavailable" in js and "is not reachable right now" in js, "UI toasts and does not crash when the peer is offline")
check(".card.unavailable" in css and "badge.off" in css, "offline shared cards have a distinct style")
check("Force a new APK" not in ch, "changelog does not claim a required APK (sanity)")
check("No new Android app" in ch or "no new Android" in ch.lower() or "no APK" in ch or "No new APK" in ch,
      "changelog says no new Android app is needed")

print("schema 14 -> 15 backup")
v243 = Path("/workspace/media-server/v243/media-server")
side = Path(TMP) / "pre14"
side.mkdir()
sub = subprocess.run(
    [sys.executable, "-c",
     "import os,sys; os.environ['MS_DATA_DIR']=%r; sys.path.insert(0,%r); from app import db; db.migrate()"
     % (str(side), str(v243))],
    cwd=str(v243), capture_output=True, text=True)
if sub.returncode != 0:
    print(sub.stderr[-800:])
    raise SystemExit("could not plant a schema-14 database")
conn = sqlite3.connect(str(side / "media-server.db"))
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
conn.close()
check(ver and ver[0] == "14", "planted database is schema 14 (got %s)" % (ver and ver[0]))

child = r"""
import os, sys, stat
from pathlib import Path
os.environ["MS_DATA_DIR"] = %r
sys.path.insert(0, %r)
from pathlib import Path as P
import app.config as cfg
cfg.DATA_DIR = P(%r)
cfg.DB_PATH = cfg.DATA_DIR / "media-server.db"
import app.db as d
d.config = cfg
d.migrate()
bak = cfg.DATA_DIR / "media-server.db.pre-schema15"
assert bak.is_file(), "missing pre-schema15"
print("BACKUP_OK", oct(bak.stat().st_mode & 0o777), bak)
c = __import__("sqlite3").connect(str(cfg.DB_PATH))
v = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
print("NEW_VER", v[0] if v else None)
has = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='remote_progress'").fetchone()
print("HAS_TABLE", bool(has))
c.close()
""" % (str(side), str(ROOT), str(side))
sub = subprocess.run([sys.executable, "-c", child], cwd=str(ROOT), capture_output=True, text=True)
if sub.returncode != 0:
    print(sub.stdout[-500:], sub.stderr[-800:])
    raise SystemExit("schema 15 migrate failed")
check("BACKUP_OK" in sub.stdout, "pre-schema15 backup was written")
mode_line = [ln for ln in sub.stdout.splitlines() if ln.startswith("BACKUP_OK")]
mode = mode_line[0].split()[1] if mode_line else "?"
check(mode in ("0o600", "0600") or mode == "0o600", "pre-schema15 mode is 600 (got %s)" % mode)
check("NEW_VER 15" in sub.stdout, "migrated database is schema 15")
check("HAS_TABLE True" in sub.stdout, "remote_progress exists after migrate")
# snapshot still schema 14
c = sqlite3.connect(str(side / "media-server.db.pre-schema15"))
v = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
c.close()
check(v and v[0] == "14", "pre-schema15 snapshot still has schema 14")

print("fresh migrate + API")
db.migrate()
keys.ensure()
auth.create_user("admin", "TestPass14!", is_admin=True)
auth.create_user("viewer", "TestView14!", is_admin=False)
settings.put("server_name", "North")
now = int(time.time())
media = Path(DATA) / "media"
media.mkdir(parents=True, exist_ok=True)
clip = media / "northstar.mp4"
clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
# a 40-char poster hash
poster = "a" * 40 + ".jpg"
(Path(DATA) / "thumbs").mkdir(parents=True, exist_ok=True)
(Path(DATA) / "thumbs" / poster).write_bytes(b"\xff\xd8\xff\xd9")

with db.tx() as c:
    c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
              ("Movies", "movies", str(media), 0, now))
    lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster) "
              "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?)",
              (lid, str(clip), "Northstar", "Northstar", 2020, now, 90001, poster))
    local_iid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen) "
              "VALUES(?,?,?,?,?,?,?,?)",
              ("srv-harbor", "Harbor", "http://192.0.2.10:8099", "ab" * 32, "incoming", "active", now, now))
    harbor = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen) "
              "VALUES(?,?,?,?,?,?,?,?)",
              ("srv-light", "Lighthouse", "http://192.0.2.11:8099", "cd" * 32, "incoming", "revoked", now, now))
    light = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count, last_sync) "
              "VALUES(?,?,?,?,?,?)",
              (harbor, 7, "Movies", "movies", 4, now))
    hlid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count, last_sync) "
              "VALUES(?,?,?,?,?,?)",
              (light, 3, "Movies", "movies", 1, now))
    llid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Harbor: twin of local Northstar, unique Last Light, a finished title, a short-position title, a nearly-done title
    rows = [
        (hlid, 101, "movie", "Northstar", 2020, 90001, "Northstar", 7200, poster),
        (hlid, 102, "movie", "The Last Light", 2019, 90002, "The Last Light", 5400, poster),
        (hlid, 103, "movie", "Finished Voyage", 2018, 90003, "Finished Voyage", 4800, poster),
        (hlid, 104, "movie", "Just Opened", 2021, 90004, "Just Opened", 6000, poster),
        (hlid, 105, "movie", "Almost Done", 2017, 90005, "Almost Done", 5000, poster),
        (llid, 201, "movie", "Harbor Night", 2016, 90006, "Harbor Night", 5100, poster),
    ]
    for rl, rid, kind, title, year, tmdb, sort, dur, post in rows:
        c.execute("INSERT INTO remote_items(remote_library_id, remote_item_id, kind, title, year, tmdb_id, sort_title, duration, poster, added_at, updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (rl, rid, kind, title, year, tmdb, sort, dur, post, now, now))

# map remote_items.id by title
by_title = {r["title"]: r["id"] for r in db.rows("SELECT id, title FROM remote_items")}
meta = db.row("SELECT value FROM meta WHERE key='schema_version'")
check(meta and meta["value"] == "15", "fresh migrate is schema 15 (got %s)" % (meta and meta["value"]))

try:
    db.get().close()
    db._local.conn = None
except Exception:
    pass

import uvicorn  # noqa: E402

PORT = 19400 + os.getpid() % 300
BASE = "http://127.0.0.1:%d" % PORT
threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                 daemon=True).start()


def req(base, path, method="GET", obj=None, cookies=None):
    url = base + path
    data = None
    headers = {"User-Agent": "ms-v25-test"}
    if obj is not None:
        data = json.dumps(obj).encode()
        headers["Content-Type"] = "application/json"
    cj = cookies if cookies is not None else CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(r, timeout=20) as resp:
            body = resp.read()
            try:
                parsed = json.loads(body.decode())
            except Exception:
                parsed = body
            return resp.status, parsed, cj
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw.decode())
        except Exception:
            parsed = raw
        return e.code, parsed, cj


def wait_up():
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/version", timeout=0.4)
            return
        except Exception:
            try:
                urllib.request.urlopen(BASE + "/", timeout=0.4)
                return
            except Exception:
                time.sleep(0.1)
    raise SystemExit("server did not start on %s" % BASE)


wait_up()
cj = CookieJar()
st, body, cj = req(BASE, "/api/login", "POST", {"username": "admin", "password": "TestPass14!"}, cookies=cj)
check(st == 200, "login admin -> %s" % st)
check(any(c.name == "ms_session" for c in cj), "login set ms_session cookie (%s)" % list(cj))

# Progress on a shared-only title
last_light = -by_title["The Last Light"]
st, body, cj = req(BASE, "/api/items/%d/progress" % last_light, "POST",
                   {"position": 640, "duration": 5400}, cookies=cj)
check(st == 200 and body.get("ok") and not body.get("watched"),
      "saving progress on a shared title succeeds (%s %s)" % (st, body))
row = db.row("SELECT position, watched FROM remote_progress WHERE remote_item_id=?", (by_title["The Last Light"],))
check(row and abs(row["position"] - 640) < 0.01 and not row["watched"],
      "remote_progress stores the position on the local catalog id")
# must not have been written to the items FK table
bad = db.row("SELECT * FROM progress WHERE item_id=?", (last_light,))
check(not bad, "negative API ids are not written to progress (FK would fail)")

# Local twin of Northstar should also receive progress when the shared copy is played
north = -by_title["Northstar"]
st, body, cj = req(BASE, "/api/items/%d/progress" % north, "POST",
                   {"position": 900, "duration": 7200}, cookies=cj)
check(st == 200, "progress on a shared title that also exists locally -> %s" % st)
lp = db.row("SELECT position FROM progress WHERE item_id=?", (local_iid,))
check(lp and abs(lp["position"] - 900) < 0.01, "local twin of the shared title got the same position")

# Finished / too-short / almost-done
req(BASE, "/api/items/%d/progress" % (-by_title["Finished Voyage"]), "POST",
    {"position": 4700, "duration": 4800, "ended": True}, cookies=cj)
req(BASE, "/api/items/%d/progress" % (-by_title["Just Opened"]), "POST",
    {"position": 12, "duration": 6000}, cookies=cj)
req(BASE, "/api/items/%d/progress" % (-by_title["Almost Done"]), "POST",
    {"position": 4800, "duration": 5000}, cookies=cj)  # 96% > 0.95, and also > 0.92 so marked watched
# Offline peer title
req(BASE, "/api/items/%d/progress" % (-by_title["Harbor Night"]), "POST",
    {"position": 400, "duration": 5100}, cookies=cj)

st, home, cj = req(BASE, "/api/home", "GET", cookies=cj)
check(st == 200, "/api/home succeeds (%s)" % st)
check(isinstance(home, dict) and "continue" in home, "home has a continue list")
cont = home["continue"]
titles = [i.get("title") for i in cont]
ids = [i.get("id") for i in cont]
check("The Last Light" in titles, "shared-only title is in Continue watching: %s" % titles)
ll = next(i for i in cont if i["title"] == "The Last Light")
check(ll["id"] == last_light, "shared title uses the negative API id")
check(abs(float(ll["position"]) - 640) < 0.01, "resume position is 640s, got %s" % ll["position"])
check(ll.get("poster"), "shared title has a poster")
check(ll.get("is_remote") and not ll.get("unavailable"), "online shared title is not marked unavailable")
check("Northstar" in titles, "shared title that also exists locally is in Continue watching")
ns = next(i for i in cont if i["title"] == "Northstar")
check(ns["id"] == local_iid, "dedupe prefers the local copy of Northstar (id %s)" % ns["id"])
check(abs(float(ns["position"]) - 900) < 0.01, "local card carries the shared resume position")
check(not ns.get("unavailable"), "local preferred card is not unavailable")
check(titles.count("Northstar") == 1, "Northstar appears once (deduped)")
check("Finished Voyage" not in titles, "finished shared title is not in Continue watching")
check("Just Opened" not in titles, "shared title under 30s is not in Continue watching")
check("Almost Done" not in titles, "shared title past 95 percent drops off Continue watching")
check("Harbor Night" in titles, "offline shared title stays in Continue watching")
hn = next(i for i in cont if i["title"] == "Harbor Night")
check(hn.get("unavailable") is True, "offline shared title is marked unavailable")
check(hn.get("peer_name") == "Lighthouse" or hn.get("source_name") == "Lighthouse",
      "unavailable card names the peer")

# details + resume
st, detail, cj = req(BASE, "/api/items/%d" % last_light, "GET", cookies=cj)
check(st == 200, "shared item detail -> %s" % st)
check(abs(float(detail.get("position") or 0) - 640) < 0.01, "detail resume position is 640s")
check(not detail.get("unavailable"), "online detail is not unavailable")
check(isinstance((detail.get("playback") or {}).get("audio_streams"), list)
      and isinstance(detail.get("directors"), list) and isinstance(detail.get("cast"), list)
      and isinstance(detail.get("tags"), list),
      "shared detail includes the lists the item page maps over")
check("(pb.audio_streams || [])" in js and "it.directors || []" in js, "item page guards missing credit / stream lists")

st, detail, cj = req(BASE, "/api/items/%d" % (-by_title["Harbor Night"]), "GET", cookies=cj)
check(st == 200 and detail.get("unavailable") is True, "offline detail is marked unavailable, not an error")

# My List
st, ml, cj = req(BASE, "/api/mylist", "GET", cookies=cj)
check(st == 200, "/api/mylist -> %s" % st)
ml_cont = [i["title"] for i in ml.get("continue") or []]
ml_watched = [i["title"] for i in ml.get("watched") or []]
check("The Last Light" in ml_cont, "My List continue includes the shared title")
check("Finished Voyage" in ml_watched or "Almost Done" in ml_watched,
      "watched shared titles appear in My List watched: %s" % ml_watched)
check("Finished Voyage" not in ml_cont, "watched shared title is not also in My List continue")

# marking watched drops it
st, body, cj = req(BASE, "/api/items/%d/watched" % last_light, "POST", {"watched": True}, cookies=cj)
check(st == 200, "mark shared title watched -> %s" % st)
st, home, cj = req(BASE, "/api/home", "GET", cookies=cj)
titles2 = [i.get("title") for i in home["continue"]]
check("The Last Light" not in titles2, "shared title drops off Continue watching when marked watched")

# local-only play does not create remote_progress for a title that was never played remotely
# (Northstar already has remote_progress from the earlier shared play -- use a new local-only film)
clip2 = media / "solo.mp4"
clip2.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
with db.tx() as c:
    c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id) "
              "VALUES(?,?, 'video','movie',?,?,?,3600,?,1,?)",
              (lid, str(clip2), "Solo Flight", "Solo Flight", 2022, now, 90007))
    solo = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO remote_items(remote_library_id, remote_item_id, kind, title, year, tmdb_id, sort_title, duration, added_at, updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)",
              (hlid, 301, "movie", "Solo Flight", 2022, 90007, "Solo Flight", 3600, now, now))
st, body, cj = req(BASE, "/api/items/%d/progress" % solo, "POST",
                   {"position": 200, "duration": 3600}, cookies=cj)
check(st == 200, "local-only progress -> %s" % st)
solo_remote = db.row("SELECT id FROM remote_items WHERE title=?", ("Solo Flight",))
rp = db.row("SELECT * FROM remote_progress WHERE remote_item_id=?", (solo_remote["id"],))
check(not rp, "playing a local title does not invent remote_progress for a matching shared copy")
st, home, cj = req(BASE, "/api/home", "GET", cookies=cj)
solo_cards = [i for i in home["continue"] if i.get("title") == "Solo Flight"]
check(len(solo_cards) == 1 and solo_cards[0]["id"] == solo, "local-only title appears once, as the local id")

# home must not 500 when a peer is down (already covered) and when continue remotes throw -- smoke
check(st == 200, "home still 200 after mixed local/remote progress")

# 404 on unknown shared id
st, body, cj = req(BASE, "/api/items/%d/progress" % (-999999), "POST",
                   {"position": 50, "duration": 100}, cookies=cj)
check(st == 404, "unknown shared id is 404, not a FK error (%s)" % st)

print()
if fails:
    print("%d FAILED:" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all ok")
