"""2.6.5: bogus display cap, transcode restart backoff, phone web player Direct Play."""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v265-"))
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
from app import db, transcode, preload, server  # noqa: E402

ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
appjs = (ROOT / "app/static/app.js").read_text()
trc = (ROOT / "app/transcode.py").read_text()
pre = (ROOT / "app/preload.py").read_text()
srv = (ROOT / "app/server.py").read_text()

print("version and docs")
check(__version__ == "2.6.5", "version is 2.6.5, got %s" % __version__)
check("## 2.6.5" in ch and ch.find("## 2.6.5") < ch.find("## 2.6.4"), "CHANGELOG has 2.6.5 above 2.6.4")
sec = ch.split("## 2.6.5", 1)[1].split("## 2.6.4", 1)[0]
check("disp=88" in sec or "88" in sec, "CHANGELOG mentions the bogus 88-pixel display")
check("1080p" in sec and "360p" in sec, "CHANGELOG mentions the 1080p cap vs 360p")
check("rate-limit" in sec.lower() or "backoff" in sec.lower() or "rate-limited" in sec.lower(),
      "CHANGELOG mentions restart rate-limiting")
check("ffmpeg.log" in sec, "CHANGELOG mentions the ffmpeg.log fix")
check("direct_maybe" in sec and "videoWidth" in sec, "CHANGELOG mentions the phone player fixes")
check("roku/" in sec.lower() and "unchanged" in sec.lower(), "CHANGELOG notes the Roku channel is unchanged")
check("**2.6.5:**" in rd, "install README mentions 2.6.5")
check(rd.find("**2.6.5:**") < rd.find("**2.6.4:**"), "README 2.6.5 bullet is above 2.6.4")
for bad in ("192.168.", "password=", "ms_session=secret", "ADMIN_PASSWORD", "BEGIN RSA"):
    check(bad not in sec, "2.6.5 changelog does not contain %r" % bad)

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)

print("1. bogus client display size")
check(transcode.device_cap_base(0, 0) is None, "missing display/decoder is still no cap")
check(transcode.device_cap_base(88, 88) == "1080p", "disp=88 dec=88 falls back to 1080p, not 360p")
check(transcode.device_cap_base(88, 0) == "1080p", "bogus display alone falls back to 1080p")
check(transcode.device_cap_base(0, 88) == "1080p", "bogus decoder alone falls back to 1080p")
check(transcode.device_cap_base(1920, 88) == "1080p", "bogus decoder is ignored; 1920 display caps at 1080p")
check(transcode.device_cap_base(88, 1920) == "1080p", "bogus display is ignored; 1920 decoder caps at 1080p")
check(transcode.device_cap_base(1280) == "720p", "a real 1280 display still caps at 720p")
check(transcode.device_cap_base(3840) == "2160p", "a real 4K display still allows 2160p")
check(transcode.device_cap_base(479, 479) == "1080p", "479 px is below the plausible floor")
check(transcode.device_cap_base(480) == "360p", "480 px is accepted and caps at 360p")
big = {"width": 3840, "height": 2160}
prof, cap, chg = transcode.clamp_profile("2160p", big, 88, 88)
check(prof == "1080p" and cap == "1080p" and chg is True,
      "clamp_profile turns 2160p + disp=88 into 1080p, not 360p (got %s/%s)" % (prof, cap))
# previously this would have been 360p
check(transcode.device_cap_base(88, 88) != "360p", "88 px is not treated as 360p")

print("2. transcode restart backoff and runaway yield")
transcode.clear_restart_guard()
item = {
    "id": 42, "title": "The Mongoose", "path": "/tmp/ms-v265-missing.mkv",
    "duration": 120, "width": 3840, "height": 2160, "vcodec": "", "media_type": "video",
}
s = transcode.Session("v265-loop", item, "720p", 0)
s.start_seg = 0
check(transcode.restart_blocked(s) is False, "a new session is not yet rate-limited")
check(transcode.is_runaway(s) is False, "a new session with no start is not runaway")
for _ in range(transcode.EMPTY_RESTART_MAX):
    transcode.note_empty_start(s)
check(transcode.restart_blocked(s) is True, "three empty starts rate-limit this session")
s.start(0)
check(s.proc is None, "start() is a no-op while backing off (does not relaunch ffmpeg)")
transcode.clear_restart_guard(s.sid)
s._backoff_until = 0
s._empty_starts = []
check(transcode.restart_blocked(s) is False, "clear_restart_guard lifts the sid backoff")

# yield a stalled session of the same file; leave a different title alone
class _DummyProc:
    def __init__(self):
        self.pid = 0
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0

transcode.clear_restart_guard()
transcode._sessions.clear()
runaway = transcode.Session("v265-runaway", item, "720p", 0)
runaway.start_seg = 0
runaway.started_at = time.time() - transcode.HW_STALL_S - 1
runaway.proc = _DummyProc()
other_item = dict(item, id=99, title="Other")
other = transcode.Session("v265-other", other_item, "720p", 0)
other.start_seg = 0
other.started_at = time.time() - transcode.HW_STALL_S - 1
other.proc = _DummyProc()
fresh = transcode.Session("v265-fresh", item, "480p", 0)
fresh.start_seg = 0
fresh.started_at = time.time()
fresh.proc = _DummyProc()
transcode._sessions.update({runaway.sid: runaway, other.sid: other, fresh.sid: fresh})
check(transcode.is_runaway(runaway) is True, "a stalled no-output session is runaway")
check(transcode.is_runaway(fresh) is False, "a just-started session is not yet runaway")
n = transcode.yield_runaway(item_id=42, keep_sid=fresh.sid)
check(n == 1, "yield_runaway stops only the runaway session of the same file (got %s)" % n)
check(runaway.proc is None, "the runaway ffmpeg was stopped")
check(transcode.restart_blocked(runaway) is True, "the yielded session is backed off")
check(other.proc is not None, "a runaway of a different file is left alone when item_id is set")
check(fresh.proc is not None, "keep_sid is not stopped")
# a new Direct Play of the same file should also yield it (via preload)
other.proc = _DummyProc()
other.started_at = time.time() - transcode.HW_STALL_S - 1
n = preload.yield_to_playback(item_id=99)
check(other.proc is None, "yield_to_playback pauses a runaway transcode of the same file")
# cleanup
for sess in (s, runaway, other, fresh):
    try:
        sess.destroyed = True
        shutil.rmtree(sess.dir, ignore_errors=True)
    except Exception:
        pass
transcode._sessions.clear()
transcode.clear_restart_guard()

print("4. FileNotFoundError on ffmpeg.log after destroy")
fnf = transcode.Session("v265-fnf", item, "720p", 0)
fnf.destroy("test")
try:
    fnf.start(0)
    check(True, "start() after destroy does not raise")
except FileNotFoundError:
    check(False, "start() after destroy raised FileNotFoundError")
    failed += 0
except Exception as e:
    check(False, "start() after destroy raised %s: %s" % (type(e).__name__, e))
check(fnf.proc is None, "destroyed session does not launch ffmpeg")

# directory gone but the destroyed flag lost the race: still no FileNotFoundError
race = transcode.Session("v265-race", item, "720p", 0)
shutil.rmtree(race.dir, ignore_errors=True)
race.destroyed = False
try:
    race.start(0)
    check(True, "start() with a missing dir does not raise FileNotFoundError")
except FileNotFoundError:
    check(False, "start() with a missing dir raised FileNotFoundError")
except Exception as e:
    # ffmpeg itself may fail later; FileNotFoundError on the log is the bug
    check("ffmpeg.log" not in str(e), "start() failed, but not on ffmpeg.log (%s)" % e)
try:
    race.destroy("cleanup")
except Exception:
    pass

print("5. phone web player: HEVC/4K direct_maybe and videoWidth watchdog")
cd = appjs.split("function canDirect", 1)[1].split("function pickVersion", 1)[0]
check("direct_maybe" in cd, "canDirect still handles direct_maybe")
check("isHevc" in cd and "longSide" in cd, "canDirect has HEVC and 4K checks")
check('return "no"' in cd and "2100" in cd, "HEVC or 4K direct_maybe returns no (transcode)")
check("hevc_el" not in cd or "isHevc" in cd,
      "HEVC direct_maybe is no longer trusted just because hevc_el is probably")
# must not still do: hevc && !hevc_el && !hevc_mse return no; else try
check('it.vcodec === "hevc" && !clientCaps().hevc_el && !clientCaps().hevc_mse' not in cd,
      "old hevc_el=probably path is gone")
hw = appjs.split("function hideWait", 1)[1].split("function ", 1)[0]
check("videoWidth > 0" in hw and "clearStartWatch()" in hw,
      "hideWait clears the start watch only when videoWidth > 0")
check("function hideWait() { clearStartWatch();" not in appjs,
      "hideWait no longer clears the watch unconditionally")
arm = appjs.split("function armStartWatch", 1)[1].split("function startStream", 1)[0]
check("videoWidth > 0" in arm, "armStartWatch decides based on videoWidth")
check("readyState >= 2 || video.videoWidth" not in arm,
      "armStartWatch no longer treats readyState >= 2 as a real picture")
check('fallback("no picture yet")' in arm, "timeout still falls back with no picture yet")
check('["playing", "canplay", "loadeddata"]' in appjs, "canplay still hides the wait overlay")

print("hooks and constants")
check("MIN_PLAUSIBLE_PX" in trc and "BOGUS_DISPLAY_CAP" in trc, "cap helpers are in transcode.py")
check("EMPTY_RESTART_MAX" in trc and "yield_runaway" in trc, "restart guard is in transcode.py")
check("cannot open ffmpeg.log" in trc, "start() warns instead of crashing on a missing log")
check("item_id=item_id" in srv.split("def direct_file", 1)[1].split("\n@", 1)[0]
      or "yield_to_playback(item_id=" in srv.split("def direct_file", 1)[1],
      "direct_file passes item_id to yield_to_playback")
check("def yield_to_playback(item_id=None" in pre, "yield_to_playback accepts item_id")
check("yield_runaway" in pre, "yield_to_playback calls yield_runaway")

if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
