"""2.6.7: do not rewind a mid-watch transcode to start=0 / seg0."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v267-"))
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
trc = (ROOT / "app/transcode.py").read_text()

print("version and docs")
check(__version__ == "2.6.7", "version is 2.6.7, got %s" % __version__)
check("## 2.6.7" in ch and ch.find("## 2.6.7") < ch.find("## 2.6.6"), "CHANGELOG has 2.6.7 above 2.6.6")
sec = ch.split("## 2.6.7", 1)[1].split("## 2.6.6", 1)[0]
check("start=0" in sec or "start-at-zero" in sec.lower() or "start at 0" in sec.lower() or "opening" in sec.lower(),
      "CHANGELOG describes the start-at-zero rewind")
check("playhead" in sec.lower() or "later" in sec.lower(), "CHANGELOG mentions keeping the playhead")
check("highest_done" in sec or "leftover" in sec.lower() or "ahead" in sec.lower(),
      "CHANGELOG mentions leftover segments / false ahead")
check("**2.6.7:**" in rd and rd.find("**2.6.7:**") < rd.find("**2.6.6:**"), "README 2.6.7 bullet is above 2.6.6")
check("def _should_ignore_backward" in trc and "def _clamp_start" in trc and "BACKWARD_SLACK" in trc,
      "transcode.py has the backward-start guards")
for bad in ("192.168.", "password=", "ms_session=secret", "ADMIN_PASSWORD", "BEGIN RSA"):
    check(bad not in sec, "2.6.7 changelog does not contain %r" % bad)

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)

item = {
    "id": 77, "title": "Mutiny", "path": "/tmp/ms-v267-missing.mkv",
    "duration": 7200, "width": 3840, "height": 2160, "vcodec": "", "media_type": "video",
}


class _DummyProc:
    def __init__(self):
        self.pid = 0
        self.killed = False

    def poll(self):
        return None if not self.killed else 1

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def _sess(sid, start_seg, last_req, running=True, segs=None):
    s = transcode.Session(sid, item, "1080p", 0)
    s.start_seg = start_seg
    s.last_req = last_req
    s.ext = "m4s"
    if running:
        s.proc = _DummyProc()
        s.paused = False
    if segs:
        s.dir.mkdir(parents=True, exist_ok=True)
        for n in segs:
            (s.dir / ("seg%d.%s" % (n, s.ext))).write_bytes(b"x")
    return s


print("1. highest_done ignores leftovers from a previous run")
s = _sess("v267-hi", start_seg=0, last_req=0, running=False, segs=range(2021, 2054))
check(s.highest_done() == -1, "leftover segs 2021-2053 after a restart at 0 are not ahead (got %s)" % s.highest_done())
shutil.rmtree(s.dir, ignore_errors=True)

s = _sess("v267-hi2", start_seg=2021, last_req=2053, running=True, segs=range(2021, 2054))
check(s.highest_done() == 2053, "a live run at 2021-2053 still reports 2053 (got %s)" % s.highest_done())
shutil.rmtree(s.dir, ignore_errors=True)

s = _sess("v267-hi3", start_seg=2021, last_req=2100, running=True, segs=range(2060, 2106))
check(s.highest_done() == 2105, "pruned opening of a late run still reports the tip (got %s)" % s.highest_done())
shutil.rmtree(s.dir, ignore_errors=True)

print("2. a live mid-watch encode is not rewound to 0")
s = _sess("v267-live", start_seg=2021, last_req=2053, running=True, segs=range(2021, 2054))
proc = s.proc
s.start(0)
check(s.proc is proc and not proc.killed, "start(0) does not stop a live mid-watch ffmpeg")
check(s.start_seg == 2021, "start_seg stays at 2021 (got %s)" % s.start_seg)
check(s.last_req == 2053, "last_req stays at 2053 after ignored start(0) (got %s)" % s.last_req)
got = s.get_segment(0, timeout=0.2)
check(got is None, "get_segment(0) does not wait on a mid-watch session (got %s)" % got)
check(s.last_req == 2053, "get_segment(0) does not clobber last_req to 0 (got %s)" % s.last_req)
check(s.proc is proc and not proc.killed, "get_segment(0) does not kill the live ffmpeg")
shutil.rmtree(s.dir, ignore_errors=True)

print("3. kickoff(0) on a dead mid-watch session restarts at the playhead")
s = _sess("v267-dead", start_seg=2021, last_req=2053, running=False)
called = []
s.start = lambda seg, _called=called: _called.append(seg)
transcode.kickoff(s, 0)
check(called == [2053], "kickoff(0) starts at last_req 2053, not 0 (got %s)" % called)
# clamp helper itself
s2 = _sess("v267-clamp", start_seg=2021, last_req=2053, running=False)
check(s2._clamp_start(0) == 2053, "_clamp_start(0) keeps 2053 (got %s)" % s2._clamp_start(0))
check(s2._clamp_start(2021) == 2021, "_clamp_start keeps the session start_seg 2021 (got %s)" % s2._clamp_start(2021))
check(s2._clamp_start(2022) == 2022, "_clamp_start allows a nearby/forward start (got %s)" % s2._clamp_start(2022))
check(s2._should_ignore_backward(0) is True, "start=0 is backward vs start_seg 2021")
check(s2._should_ignore_backward(2021) is False, "a playlist reload at the session start_seg is not backward")
check(s2._should_ignore_backward(2053) is False, "a request at last_req is not backward")

print("4. kickoff(0) is a no-op on a live mid-watch session")
s = _sess("v267-kick-live", start_seg=2021, last_req=2053, running=True)
called = []
s.start = lambda seg, _called=called: _called.append(seg)
transcode.kickoff(s, 0)
check(called == [], "kickoff(0) does not start() a live session (got %s)" % called)
check(s.start_seg == 2021 and s.last_req == 2053, "live kickoff(0) leaves start_seg and last_req alone")

print("5. a first play from the opening is still allowed")
s = _sess("v267-first", start_seg=0, last_req=0, running=False)
check(s._should_ignore_backward(0) is False, "start=0 at the beginning of a session is not ignored")
check(s._clamp_start(0) == 0, "_clamp_start(0) on a fresh session stays 0")
check(s._should_ignore_backward(2021) is False, "resuming at 2021 on a fresh session is allowed")

# cleanup
transcode._sessions.clear()
shutil.rmtree(TMP, ignore_errors=True)

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("all passed")
