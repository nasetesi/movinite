"""2.2: remux-ready play path, 5.1 audio, HDR tone-map setting, trickplay, Up Next, TV 4K cap."""
import json, os, shutil, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v22-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

failed = 0
def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)

css = (ROOT / "app/static/style.css").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
appjs = (ROOT / "app/static/app.js").read_text()
html = (ROOT / "app/static/index.html").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
dbpy = (ROOT / "app/db.py").read_text()
srv = (ROOT / "app/server.py").read_text()
hw = (ROOT / "app/hwaccel.py").read_text()
pre = (ROOT / "app/preload.py").read_text()

from app.version import __version__
from app import db, transcode, hwaccel, trickplay, preload, settings, config
from app.server import playback_info

def film(w=1920, h=1080, codec="h264", **extra):
    it = {"id": 1, "path": "/tmp/f.mkv", "width": w, "height": h, "vcodec": codec,
          "media_type": "video", "duration": 6000, "bitrate": 8000000, "mtime": 1.0,
          "container": "matroska,webm", "pix_fmt": "yuv420p",
          "audio_streams": "[]", "subtitle_streams": "[]", "external_subs": "[]",
          "acodec": "aac"}
    it.update(extra)
    return it

print("source and docs")
check(__version__ == "2.2", "version is 2.2")
check("## 2.2" in ch and ch.find("## 2.2") < ch.find("## 2.1.4"), "CHANGELOG has 2.2 above 2.1.4")
check("schema 13" in ch.split("## 2.1.4")[0].lower() or "schema 13" in ch.lower(), "changelog mentions schema 13")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("2.2" in rd, "README mentions 2.2")
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")

print("schema 13 and backup")
check("SCHEMA_VERSION = 13" in dbpy, "SCHEMA_VERSION is 13")
check("CREATE TABLE IF NOT EXISTS trickplay_cache" in dbpy, "trickplay_cache table")
check('("items", "color_primaries"' in dbpy and '("items", "color_space"' in dbpy, "color_primaries and color_space columns")
check("_backup_db(c, 13)" in dbpy, "migrate snapshots the DB before schema 13")
check("chmod(0o600)" in dbpy, "schema backups are mode 600")
check("TRICKPLAY_DIR" in (ROOT / "app/config.py").read_text(), "TRICKPLAY_DIR is configured")

# Simulate 12 -> 13 backup
db.migrate()
# rewrite meta to 12 and drop trickplay to force a bump path
data = Path(os.environ["MS_DATA_DIR"])
# start a clean 12-like db in a sibling dir
TMP2 = Path(tempfile.mkdtemp(prefix="ms-v22-s12-"))
os.environ["MS_DATA_DIR"] = str(TMP2 / "data")
(TMP2 / "data").mkdir()
# reload config paths? config.DATA_DIR is set at import. Don't rely on changing env after import.
# Instead call _backup_db against the already-migrated 13 db after forcing version 12 is messy.
# Directly test _backup_db + migrate from a fresh folder by patching config.
os.environ["MS_DATA_DIR"] = str(TMP / "data")  # restore

# Use db._backup_db on a connection after creating a fake pre-13 state in a new file via config monkeypatch
import importlib
old_data, old_db = config.DATA_DIR, config.DB_PATH
s12 = TMP / "s12"
s12.mkdir()
config.DATA_DIR = s12
config.DB_PATH = s12 / "media-server.db"
# build a schema-12 database
c = db.connect()
c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
c.execute("INSERT INTO meta(key,value) VALUES('schema_version','12')")
c.commit(); c.close()
# migrate should backup then bump
db.migrate()
bak = s12 / "media-server.db.pre-schema13"
check(bak.is_file(), "pre-schema13 backup was written")
check(oct(bak.stat().st_mode & 0o777) == "0o600", "pre-schema13 backup is mode 600")
ver = db.row("SELECT value FROM meta WHERE key='schema_version'")["value"]
check(ver == "13", "migrate bumps schema to 13 (got %s)" % ver)
check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='trickplay_cache'"),
      "trickplay_cache exists after migrate")
# second migrate must not overwrite the first backup
mtime = bak.stat().st_mtime
time.sleep(0.05)
db.migrate()
check(abs(bak.stat().st_mtime - mtime) < 0.001 or bak.stat().st_mtime == mtime, "second migrate does not replace the backup")
config.DATA_DIR, config.DB_PATH = old_data, old_db

# continue tests against the original TMP db (already migrated to 13)
os.environ["MS_DATA_DIR"] = str(TMP / "data")

print("remux only when a plan is cached")
hevc = film(w=3840, h=2160, codec="hevc", pix_fmt="yuv420p10le", id=42)
check(transcode.remux_eligible(hevc), "4K HEVC mkv is remux-eligible")
check(not transcode.remux_ready(hevc), "remux is not ready without a keyframe plan")
# playback_info must not advertise remux
pb = playback_info(hevc)
check(pb.get("remux") is False, "playback_info.remux is false when the plan is missing")
check(pb.get("remux_pending") is True, "playback_info.remux_pending is true when eligible but uncached")
# client canRemux uses pb.remux — confirm JS
check("function canRemux(pb)" in appjs and "if (!pb || !pb.remux) return false" in appjs,
      "client only remuxes when playback_info.remux is true")
check("remux_pending" in srv, "server exposes remux_pending")
# cache a plan (keyframes references items; items references libraries)
with db.tx() as c:
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("INSERT OR REPLACE INTO keyframes(item_id, mtime, data, status, checked_at, attempts) VALUES(?,?,?,?,?,?)",
              (42, 1.0, json.dumps([0.0, 2.0, 4.0, 6.0]), "ok", int(time.time()), 0))
check(transcode.remux_ready(hevc), "remux is ready once a plan is cached")
pb2 = playback_info(hevc)
check(pb2.get("remux") is True, "playback_info.remux is true when the plan is cached")
check(pb2.get("remux_pending") is False, "remux_pending is false when ready")
check("LIMIT 80" in pre and "k.item_id IS NULL" in pre, "idle remux backfill prefers titles with no plan")
check("never during" in pre.lower() or "if busy():" in pre, "preload still yields when a stream is busy")

print("5.1 audio")
src = film(audio_streams=json.dumps([{"codec": "aac", "channels": 6, "index": 0}]))
s = transcode.Session("a51", src, "remux", 0, bounds=[0.0, 2.0, 4.0], surr=6)
cmd = " ".join(s._remux_cmd(0))
check("-c:a copy" in cmd or " -c:a copy" in cmd.replace("  ", " "), "remux copies 5.1 AAC when the client wants surround")
s2 = transcode.Session("a51s", src, "remux", 0, bounds=[0.0, 2.0, 4.0], surr=0)
cmd2 = " ".join(s2._remux_cmd(0))
check("-ac 2" in cmd2 and "aac" in cmd2, "remux downmixes 5.1 AAC to stereo when the client has no surround")
ac3 = film(audio_streams=json.dumps([{"codec": "eac3", "channels": 6, "index": 0}]), acodec="eac3")
s3 = transcode.Session("eac", ac3, "remux", 0, bounds=[0.0, 2.0, 4.0], surr=6)
cmd3 = " ".join(s3._remux_cmd(0))
check("-c:a aac" in cmd3 and "-ac 6" in cmd3, "remux encodes EAC3 5.1 to AAC 5.1 for a surround client")
s4 = transcode.Session("tc51", film(audio_streams=json.dumps([{"codec": "aac", "channels": 6}])), "1080p", 0, surr=6)
# transcode _cmd may try hw; still includes audio args
cmd4 = " ".join(s4._cmd(0))
check("-c:a aac" in cmd4 and "-ac 6" in cmd4, "transcode keeps 5.1 AAC when the client wants surround")
s5 = transcode.Session("tc2", film(audio_streams=json.dumps([{"codec": "aac", "channels": 6}])), "1080p", 0, surr=0)
cmd5 = " ".join(s5._cmd(0))
check("-ac 2" in cmd5, "transcode is stereo when the client cannot do surround")
check("surr=6" in appjs and "clientCaps().surr" in appjs, "the player sends surr=6 when AAC plays")

print("HDR tone-map setting (off by default)")
check(hwaccel.hdr_tonemap_enabled() is False, "hdr_tonemap defaults to off")
vf = hwaccel._vaapi_scale("-2", 1080, "HDR10")
check("tonemap_vaapi" not in vf, "HDR10 does not tone-map while the setting is off")
vf_sdr = hwaccel._vaapi_scale("-2", 1080, "")
check("tonemap_vaapi" not in vf_sdr, "10-bit SDR / empty hdr never uses tonemap_vaapi")
settings.put("hdr_tonemap", "1")
check(hwaccel.hdr_tonemap_enabled() is True, "setting turns tone-mapping on")
if hwaccel.has_filter("tonemap_vaapi"):
    vf_on = hwaccel._vaapi_scale("-2", 1080, "HDR10")
    check("tonemap_vaapi" in vf_on and "format=p010" in vf_on, "HDR10 uses tonemap_vaapi when enabled")
    vf_hlg = hwaccel._vaapi_scale("-2", 1080, "HLG")
    check("tonemap_vaapi" in vf_hlg, "HLG uses tonemap_vaapi when enabled")
    vf_bt = hwaccel._vaapi_scale("-2", 1080, "")
    check("tonemap_vaapi" not in vf_bt, "empty/bt709 still not tone-mapped when the setting is on")
else:
    print("  skip  this ffmpeg has no tonemap_vaapi (filter check)")
settings.put("hdr_tonemap", "0")
check("Enable GPU tone mapping" in appjs, "Settings > Transcoding has the tone-map toggle")
check("off by default" in appjs.lower() or "Off by default" in appjs, "UI says tone-map is off by default")
check("hdr_tonemap" in srv, "settings API accepts hdr_tonemap")
check('hdr_tonemap' in appjs and 'with GPU tone-mapping' in appjs, "player note changes when tone-mapping is on")
check("def _do_one_color" in pre, "idle job backfills colour tags")

print("trickplay")
check("function loadTrickplay" in appjs and "function showTrickplayTip" in appjs, "player loads and shows seek-bar thumbs")
check("pl-tip-th" in html and "pl-tip-th" in css, "seek tip has a thumbnail box")
check("/api/items/{item_id}/trickplay" in srv, "trickplay API is mounted")
check("trickplay_cache_gb" in srv and "Seek-bar thumbnails" in appjs, "trickplay cache size is in Settings")
info = trickplay.public_info(film(id=99))
check(info is None, "public_info is None when nothing is cached")
# write a fake ready cache
d = trickplay.item_dir(7)
d.mkdir(parents=True, exist_ok=True)
(d / "sheet0.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 200)  # not a real jpeg; API still lists it
with db.tx() as c:
    c.execute("INSERT OR REPLACE INTO trickplay_cache(item_id, mtime, interval_s, width, height, columns, rows, "
              "count, sheets, dir, size, status, last_access, checked_at, attempts) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (7, 1.0, 10, 160, 90, 10, 10, 12, 1, str(d.relative_to(config.DATA_DIR)), 203, "ready",
               int(time.time()), int(time.time()), 0))
info = trickplay.public_info(film(id=7, mtime=1.0))
check(info and info["count"] == 12 and info["sheets"][0].endswith("/trickplay/sheet0.jpg"),
      "public_info returns sheet URLs for a ready title")
check(trickplay.sheet_path(7, 0) and trickplay.sheet_path(7, 0).is_file(), "sheet_path finds sheet0.jpg")
check("preload.busy()" in (ROOT / "app/trickplay.py").read_text(), "trickplay build yields to a live stream")

print("Up Next + honest start")
check('id="pl-upnext"' in html and "const UP =" in appjs, "Up Next card markup and logic")
check("pl-upnext-cancel" in html and "this.cancel" in appjs, "Up Next has a Cancel action")
check("Starts in " in appjs and "Play now" in html, "Up Next has a countdown and Play now")
check("UP.reset()" in appjs and "UP.tick()" in appjs, "Up Next is reset per play and ticked on timeupdate")
check("if (P && P.it.next && !UP.cancelled) UP.go()" in appjs, "ended only auto-starts when not cancelled")
check('id="pl-wait"' in html and "function showWait" in appjs, "starting overlay exists")
check("Starting remux" in appjs and "Starting transcode" in appjs and "Starting direct play" in appjs,
      "start overlay names the real mode")
check("startFragPrefetch: true" in appjs or "startFragPrefetch:!0" in appjs or "startFragPrefetch: true" in appjs.replace(" ", ""),
      "hls.js prefetches the first fragment")
check("Waiting for the first picture" in appjs, "status line says when it is waiting for the first picture")
check("hideWait()" in appjs, "the overlay is cleared when playback starts")

print("TV 4K cap + 2.1.4 navigation kept")
check("function display4kPref" in appjs and "function setDisplay4k" in appjs, "4K display preference helpers")
check('This is a 4K display' in appjs and "display4k" in appjs, "account settings include a 4K display control")
check("if (css >= 1920) return 3840" in appjs, "TV auto mode does not cap a 1920 CSS WebView at 1080p")
check("pref === \"off\"" in appjs, "the user can force a 1080p cap")
# 2.1.4 nav must stay
check("focusRail" in tvjs, "Left from the first poster still focuses the rail")
check("this.openMenu(cur)" in tvjs, "Left on the rail still opens the slide-out")
check("openMenu(null, \"lib\")" not in tvjs and "openMenu(null, 'lib')" not in tvjs, "Libraries tab does not open the menu")
check("#tv-tabs button.tv-focused" in tvcss and "#tv-rail button.tv-focused" in tvcss, "tabs and rail keep a visible focus")
check("keepFocus: true" in tvjs or "keepFocus:true" in tvjs, "tab focus-follow still keeps the tab focused")
check("armPreview" in tvjs and "250" in tvjs, "tabs/menu still activate after ~250 ms")
check('act === "signout"' in tvjs, "Sign out still needs OK")
check("block === \"start\"" in appjs and "scrollTop = 0" in appjs, "movie page still pins Play at the top")

print("public docs hygiene")
check("192.0.2.10" in rd, "README still uses the documentation IP")

# cleanup
config.DATA_DIR, config.DB_PATH = old_data, old_db
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(TMP2, ignore_errors=True)

print()
if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
