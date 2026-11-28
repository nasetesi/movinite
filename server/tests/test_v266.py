"""2.6.6: circular first-load / rebuffer ring, honest progress, 12s fallback intact."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v266-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ.pop("MS_TMDB_KEY", None)

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)


from app.version import __version__
from app import db, transcode  # noqa: E402

ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
appjs = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
html = (ROOT / "app/static/index.html").read_text()
srv = (ROOT / "app/server.py").read_text()
trc = (ROOT / "app/transcode.py").read_text()

print("version and docs")
check(__version__ == "2.6.6", "version is 2.6.6, got %s" % __version__)
check("## 2.6.6" in ch and ch.find("## 2.6.6") < ch.find("## 2.6.5"), "CHANGELOG has 2.6.6 above 2.6.5")
sec = ch.split("## 2.6.6", 1)[1].split("## 2.6.5", 1)[0]
check("ring" in sec.lower() and "9637FA" not in sec or "purple" in sec.lower(),
      "CHANGELOG describes the purple ring")
check("play-start" in sec or "first-segment" in sec or "segment" in sec.lower(),
      "CHANGELOG mentions real start progress")
check("videoWidth" in sec, "CHANGELOG keeps the videoWidth hide rule")
check("12-second" in sec or "12 s" in sec or "12-second" in sec.lower() or "12-second no-picture" in sec,
      "CHANGELOG keeps the 12s fallback")
check("Buffering" in sec, "CHANGELOG mentions replacing Buffering")
check("**2.6.6:**" in rd and rd.find("**2.6.6:**") < rd.find("**2.6.5:**"), "README 2.6.6 bullet is above 2.6.5")
for bad in ("192.168.", "password=", "ms_session=secret", "ADMIN_PASSWORD", "BEGIN RSA"):
    check(bad not in sec, "2.6.6 changelog does not contain %r" % bad)

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)

print("overlay markup and styles")
check('id="pl-ring"' in html and 'role="progressbar"' in html, "wait overlay has a progress ring")
check('class="pl-ring-fill"' in html or 'id="pl-ring-fill"' in html, "ring has a fill arc")
check('class="spin"' not in html.split('id="pl-wait"', 1)[1].split("pl-cues", 1)[0],
      "the small spinner is gone from the wait overlay")
check(".pl-ring" in css and "pl-ring-spin" in css, "CSS defines the ring and the spin animation")
check("var(--acc" in css[css.find(".pl-ring-fill"):css.find(".pl-ring-fill")+400]
      or "#9637FA" in css[css.find(".pl-ring-fill"):css.find(".pl-ring-fill")+400],
      "ring fill uses the Movinite purple accent")
check(".pl-ring.indeterminate" in css, "indeterminate spin is a CSS class")

print("player logic")
check("const START_BUFFER_S = 2" in appjs, "2-second buffered start threshold")
check("function setRingProgress" in appjs and "function loadProgressFrac" in appjs,
      "ring progress helpers exist")
check("function startLoadProgress" in appjs and "function tickLoadProgress" in appjs,
      "start/tick load progress exist")
check("/play-start" in appjs, "player polls /play-start")
check("FRAG_LOADED" in appjs, "HLS fragment loads update the ring")
check("showWait(\"Buffering" not in appjs, "waiting no longer shows Buffering…")
# mid-play uses an empty title
check('showWait("")' in appjs, "mid-play rebuffer shows the ring without a Buffering title")
hw = appjs.split("function hideWait", 1)[1].split("function ", 1)[0]
check("videoWidth > 0" in hw and "clearStartWatch()" in hw,
      "hideWait still ties the watchdog to videoWidth > 0")
check("function hideWait() { clearStartWatch();" not in appjs,
      "hideWait does not clear the watch unconditionally")
check("hideWait(true)" in appjs, "teardown force-hides the overlay")
# 12s fallback still present and still waits for videoWidth
arm = appjs.split("function armStartWatch", 1)[1].split("function startStream", 1)[0]
check("DIRECT_START_MS" in appjs and "12000" in appjs, "12s Direct Play start timeout remains")
check("videoWidth > 0" in arm and 'fallback("no picture yet")' in arm,
      "12s watchdog still falls back only when there is no picture")
check("readyState >= 2 || video.videoWidth" not in arm,
      "watchdog still does not treat readyState as a real picture")
# never invent a percent
check("invent" in appjs or "do not invent" in appjs or "never invent" in appjs
      or "no percentage is invented" in ch or "do not invent" in appjs.lower()
      or "not invent" in appjs,
      "code or docs say we do not invent a percentage")
check("setRingProgress(null)" in appjs or "return null;" in appjs.split("function loadProgressFrac", 1)[1][:800],
      "loadProgressFrac returns null when no real signal is known")

print("start_progress API")
check("def start_progress" in trc and "START_SEGS_NEEDED" in trc, "transcode.start_progress exists")
check("/api/items/{item_id}/play-start" in srv and "play_start_progress" in srv,
      "GET /api/items/{id}/play-start is wired")

transcode.clear_restart_guard()
transcode._sessions.clear()
item = {
    "id": 77, "title": "Ring Test", "path": "/tmp/ms-v266-missing.mkv",
    "duration": 120, "width": 1920, "height": 1080, "vcodec": "", "media_type": "video",
}
empty = transcode.start_progress(77, user_id=1, player_id="p1")
check(empty["ready"] == 0 and empty["need"] == 1 and empty["found"] is False,
      "no session yet returns ready=0 found=false (got %s)" % empty)

s = transcode.Session("v266-start", item, "720p", 0)
s.user_id = 1
s.player_id = "p1"
s.start_seg = 10
transcode._sessions[s.sid] = s
peek = transcode.start_progress(77, user_id=1, player_id="p1")
check(peek["found"] is True and peek["ready"] == 0 and peek["need"] == 1,
      "a session with no segments reports ready=0 (got %s)" % peek)
# a different user must not see it
other = transcode.start_progress(77, user_id=2, player_id="p1")
check(other["found"] is False, "another user does not see this session")

# write one complete segment at the start_seg
seg = s.dir / ("seg%d.%s" % (s.start_seg, s.ext))
seg.write_bytes(b"fake-ts")
peek2 = transcode.start_progress(77, user_id=1, player_id="p1")
check(peek2["ready"] == 1, "one ready start segment reports ready=1 (got %s)" % peek2["ready"])

# cleanup
s.destroyed = True
shutil.rmtree(s.dir, ignore_errors=True)
transcode._sessions.clear()

if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
