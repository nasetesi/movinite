"""2.3: Skip Intro / Credits, image-subtitle burn-in, auto-skip prefs. 2.2 / 2.1.4 kept."""
import json, os, shutil, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v23-"))
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
sip = (ROOT / "app/skipintro.py").read_text()
trp = (ROOT / "app/transcode.py").read_text()

from app.version import __version__
from app import db, transcode, hwaccel, skipintro, preload, settings, config, auth
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
check(__version__ in ("2.3", "2.4"), "version is 2.3 or later")
check("## 2.3" in ch and ch.find("## 2.3") < ch.find("## 2.2"), "CHANGELOG has 2.3 above 2.2")
check("schema 14" in ch.split("## 2.2")[0].lower() or "schema 14" in ch.lower(), "changelog mentions schema 14")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("2.3" in rd, "README mentions 2.3")
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")

print("schema 14 and backup")
check("SCHEMA_VERSION = 14" in dbpy, "SCHEMA_VERSION is 14")
check("CREATE TABLE IF NOT EXISTS intro_cache" in dbpy, "intro_cache table")
check("auto_skip_intro" in dbpy and "auto_skip_credits" in dbpy, "per-user auto-skip columns")
check("_backup_db(c, 14)" in dbpy, "migrate snapshots the DB before schema 14")
check("chmod(0o600)" in dbpy, "schema backups are mode 600")
check("INTRO_DIR" in (ROOT / "app/config.py").read_text(), "INTRO_DIR is configured")
check("items_drop_intro" in dbpy, "intro_cache is dropped with the item")

db.migrate()
old_data, old_db = config.DATA_DIR, config.DB_PATH
s13 = TMP / "s13"
s13.mkdir()
config.DATA_DIR = s13
config.DB_PATH = s13 / "media-server.db"
c = db.connect()
c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
c.execute("INSERT INTO meta(key,value) VALUES('schema_version','13')")
c.commit(); c.close()
db.migrate()
bak = s13 / "media-server.db.pre-schema14"
check(bak.is_file(), "pre-schema14 backup was written")
check(oct(bak.stat().st_mode & 0o777) == "0o600", "pre-schema14 backup is mode 600")
ver = db.row("SELECT value FROM meta WHERE key='schema_version'")["value"]
check(ver == "14", "migrate bumps schema to 14 (got %s)" % ver)
check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='intro_cache'"),
      "intro_cache exists after migrate")
mtime = bak.stat().st_mtime
time.sleep(0.05)
db.migrate()
check(bak.stat().st_mtime == mtime, "second migrate does not replace the backup")
config.DATA_DIR, config.DB_PATH = old_data, old_db
os.environ["MS_DATA_DIR"] = str(TMP / "data")

print("chapter + fingerprint + credits detection")
chs = skipintro.parse_chapters("""
[CHAPTER]
TIMEBASE=1/1000
START=0
start_time=0.000000
end_time=85.000000
title=Previously
[CHAPTER]
start_time=85.000
end_time=145.000
title=Opening Credits
[CHAPTER]
start_time=146.000
end_time=2400.000
title=Main
[CHAPTER]
start_time=2460.000
end_time=2580.000
title=End Credits
""")
check(len(chs) == 4, "parse_chapters reads four chapters")
s, e, cred = skipintro.markers_from_chapters(chs, 2580)
check(s == 0.0 and e == 145.0, "recap + intro merge into one skip region (got %s-%s)" % (s, e))
check(cred == 2460.0, "end credits chapter is credits_start")
# fake fingerprints: a distinctive 20s intro starting at 8s in A and 10s in B (0.2s frames)
def run(pad_before, dur_s, pad_after, pre, post, mid_seed=0x5A):
    fb = [pre] * int(round(pad_before / 0.2))
    mid = [mid_seed ^ ((i * 13) & 0x7F) for i in range(int(round(dur_s / 0.2)))]
    fa = [post] * int(round(pad_after / 0.2))
    return fb + mid + fa
A = run(8, 20, 40, pre=0x11, post=0xF0)
B = run(10, 20, 30, pre=0xEE, post=0x0F)
hit = skipintro.match_seconds(A, B)
check(hit and abs(hit["start_a"] - 8) <= 0.4 and abs(hit["start_b"] - 10) <= 0.4,
      "fingerprint match finds the shared intro (got %s)" % hit)
check(hit and abs(hit["duration"] - 20) <= 0.6, "matched intro is ~20s")
cons = skipintro.consensus_intro({1: [(8.0, 28.0), (8.1, 28.2)], 2: [(10.0, 30.0), (9.9, 29.8)]})
check(1 in cons and 2 in cons, "consensus intro needs agreeing pairs")
# black/silence at the end (timestamps relative to a 600s window starting at 3000 in a 3600s file)
logtxt = """
[blackdetect @ 0x1] black_start:480.0
[blackdetect @ 0x1] black_end:598.0 black_duration:118.0
[silencedetect @ 0x2] silence_start: 479.5
[silencedetect @ 0x2] silence_end: 598.2 | silence_duration: 118.7
"""
cs = skipintro.parse_black_silence(logtxt, 3600, 3000)
check(cs is not None and abs(cs - 3480) < 2, "blackdetect in a seek window maps to file time (got %s)" % cs)
check("yield" in sip.lower() and "preload.busy()" in sip or "def _busy" in sip, "intro work yields to playback")
check("fpcalc" in sip and "extract_pcm" in sip, "fpcalc is optional; ffmpeg PCM is the fallback")
check("skipintro._do_one" in pre, "idle tick runs intro detection")

print("image subtitles + burn-in")
subs = json.dumps([
    {"index": 2, "codec": "subrip", "lang": "eng", "title": "English", "text": True},
    {"index": 3, "codec": "hdmv_pgs_subtitle", "lang": "eng", "title": "English", "text": False},
    {"index": 4, "codec": "dvd_subtitle", "lang": "spa", "title": "Spanish", "text": False},
])
pb = playback_info(film(subtitle_streams=subs))
keys = {s["key"]: s for s in pb["subtitles"]}
check("s2" in keys and not keys["s2"].get("burn"), "text subs stay soft (no burn flag)")
check("s3" in keys and keys["s3"].get("burn") and "PGS" in keys["s3"]["label"], "PGS is listed and marked to burn")
check("s4" in keys and "VobSub" in keys["s4"]["label"], "VobSub is listed")
check(any(s.get("codec") == "hdmv_pgs_subtitle" for s in pb["image_subs"]), "image_subs still lists PGS")

hwaccel._filters = {"overlay_vaapi", "scale_vaapi", "tonemap_vaapi"}
fc = hwaccel.burn_filter_complex("full", "vaapi", 1920, 1080, 3, base_video_f="scale_vaapi=w=1920:h=1080:format=nv12")
check("overlay_vaapi" in fc and "hwupload" in fc and "[0:3]" in fc, "full VAAPI path uses overlay_vaapi and uploads only the subtitle plane")
hwaccel._filters = {"scale_vaapi"}  # no overlay_vaapi
fc2 = hwaccel.burn_filter_complex("enc", "vaapi", 1920, 1080, 3)
check("overlay=" in fc2 and "hwupload" in fc2 and "overlay_vaapi" not in fc2,
      "without overlay_vaapi, CPU overlay then hwupload")
hwaccel._filters = None  # re-detect later if needed

s_txt = transcode.Session("noburn", film(), "1080p", 0, surr=0, burn=0)
cmd_t = " ".join(s_txt._cmd(0))
check(" -sn " in (" " + cmd_t + " ") or cmd_t.endswith("-sn") or " -sn " in cmd_t,
      "text/off still drops subtitle streams with -sn")
s_b = transcode.Session("burnpgs", film(), "1080p", 0, surr=0, burn=3)
cmd_b = " ".join(s_b._cmd(0))
check("-filter_complex" in cmd_b and "[0:3]" in cmd_b, "burn session uses filter_complex on stream 3")
check(" -sn " not in (" " + cmd_b + " ") and "-sn" not in cmd_b.split(), "burn session does not pass -sn")
check("overlay" in cmd_b, "burn session includes an overlay filter")
sid0 = transcode.session_id(1, "1080p", 0, 1, "p", 0, 0)
sid1 = transcode.session_id(1, "1080p", 0, 1, "p", 0, 3)
check(sid0 != sid1, "session id changes when the burned subtitle changes")
s_r = transcode.Session("remux", film(), "remux", 0, bounds=[0.0, 2.0, 4.0], surr=0, burn=3)
cmd_r = " ".join(s_r._remux_cmd(0))
check("-sn" in cmd_r, "remux still uses -sn (cannot burn while copying video)")
check("burn=" in appjs and "isBurnSub" in appjs, "the player sends burn= and detects image tracks")
check("Image subtitles" in appjs or "burned in" in appjs, "switching to remux/direct with PGS is explained")
check("/api/items/{item_id}/hls/{profile}/index.m3u8" in srv and "burn: int" in srv, "HLS routes accept burn=")

print("Skip Intro UI + auto-skip prefs")
check('id="pl-skip-intro"' in html and 'id="pl-skip-credits"' in html, "Skip Intro and Skip Credits buttons exist")
check("Skip Intro" in html and "Skip Credits" in html, "button labels are present")
check("const SK =" in appjs and "SK.skipIntro" in appjs and "SK.skipCredits" in appjs, "skip controller exists")
check("UP.show" in appjs and "skipCredits" in appjs, "Skip Credits ties into Up Next")
check("/api/me/prefs" in srv and "auto_skip_intro" in srv, "per-user auto-skip prefs API")
check("askip-i" in appjs and "Auto-skip intros" in appjs, "Settings > Account has auto-skip toggles")
check("auto_skip_intro" in srv and "auto_skip_credits" in appjs, "prefs are on /api/me and the account page")
check("pl-skip-intro" in appjs and "TV.focus" in appjs, "Skip Intro is focused on a TV when it appears")
check(".pl-skip" in css and "tv-focused" in css and "pl-skip:focus" in css, "skip buttons have a visible TV focus ring")
check("/api/items/{item_id}/markers" in srv, "markers API is mounted")

print("2.2 and 2.1.4 kept")
check("function canRemux(pb)" in appjs, "2.2 remux-ready client check remains")
check('id="pl-upnext"' in html and "const UP =" in appjs, "Up Next card remains")
check("function loadTrickplay" in appjs, "trickplay remains")
check("if (css >= 1920) return 3840" in appjs, "TV 4K cap fix remains")
check("focusRail" in tvjs, "Left from the first poster still focuses the rail")
check("this.openMenu(cur)" in tvjs, "Left on the rail still opens the slide-out")
check("openMenu(null, \"lib\")" not in tvjs and "openMenu(null, 'lib')" not in tvjs, "Libraries tab does not open the menu")
check("#tv-tabs button.tv-focused" in tvcss and "#tv-rail button.tv-focused" in tvcss, "tabs and rail keep a visible focus")
# tv-plex.js must be unchanged vs 2.2
v22 = Path("/workspace/media-server/v22/media-server/app/static/tv-plex.js")
if v22.is_file():
    check(v22.read_text() == tvjs, "tv-plex.js is unchanged from 2.2")

print("public docs hygiene")
check("192.0.2.10" in rd, "README still uses the documentation IP")

config.DATA_DIR, config.DB_PATH = old_data, old_db
shutil.rmtree(TMP, ignore_errors=True)

print()
if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
