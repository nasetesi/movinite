"""2.6.9: mid-watch resume playlist starts at start_seg; HEVC remux has a stage.

Run: python3 tests/test_v269.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MS_DATA_DIR", "/tmp/ms-test-data-269")

from app.version import __version__
from app import transcode, config

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)


ITEM = {
    "id": 1642,
    "duration": 13698.396,
    "media_type": "video",
    "container": "matroska,webm",
    "vcodec": "hevc",
    "width": 3840,
    "height": 1610,
    "mtime": 1,
    "audio_streams": '[{"index": 1, "codec": "aac", "channels": 6}]',
}
BOUNDS = [0.0, 3.2, 6.4, 9.5, 12.7, 16.0, 19.2, 22.4, 25.6, 28.8]
SHORT = dict(ITEM, duration=30.0, id=1)


print("version")
check(__version__ == "2.6.9", "version is 2.6.9, got %s" % __version__)

print("mid-start transcode playlist")
pl = transcode.playlist(ITEM, "?session=x", None, None, start=47)
check("#EXT-X-MEDIA-SEQUENCE:47" in pl, "MEDIA-SEQUENCE is 47, got first lines:\n%s" % "\n".join(pl.splitlines()[:8]))
check("seg47.ts?session=x" in pl, "first listed segment is seg47.ts")
check("seg0.ts" not in pl, "playlist does not advertise seg0.ts")
# default start=0 still lists from the opening (2.6.8 shape)
pl0 = transcode.playlist(ITEM, "?session=x")
check("#EXT-X-MEDIA-SEQUENCE:0" in pl0 and "seg0.ts?session=x" in pl0,
      "start=0 still lists from segment 0")

print("mid-start fMP4 / HEVC playlist")
plh = transcode.playlist(SHORT, "?session=x", None, "init.mp4?session=x", start=7)
check("#EXT-X-MEDIA-SEQUENCE:7" in plh, "fMP4 MEDIA-SEQUENCE is 7")
check("seg7.m4s?session=x" in plh and "seg0.m4s" not in plh, "fMP4 playlist starts at seg7.m4s")
check('#EXT-X-MAP:URI="init.mp4?session=x"' in plh, "fMP4 map is kept when start>0")

print("bounded H.264 remux playlist respects start")
plb = transcode.playlist(dict(SHORT, vcodec="h264"), "?session=x", BOUNDS, None, start=4)
check("#EXT-X-MEDIA-SEQUENCE:4" in plb and "seg4.ts?session=x" in plb and "seg0.ts" not in plb,
      "bounded playlist starts at the requested segment")

print("ignored backward segment is 404, not 500")
with tempfile.TemporaryDirectory() as td:
    config.TRANSCODE_DIR = Path(td)
    # vcodec left empty so Session() does not call hwaccel.active() (needs a settings table).
    s = transcode.Session("v269-resume", dict(ITEM, vcodec=""), "1080p", 0)
    s.start_seg = 47
    s.last_req = 0
    # Pretend ffmpeg is running later in the title (do not spawn a process).
    s.proc = type("P", (), {"poll": staticmethod(lambda: None)})()
    check(s._should_ignore_backward(0) is True, "seg0 is backward vs start_seg 47")
    check(s.get_segment(0, timeout=0.01) is None, "get_segment(0) returns None without waiting")
    check(s.last_req == 0, "last_req stays 0 when seg0 is ignored")
    check(transcode.segment_missing_status(s, 0) == 404,
          "ignored backward miss is HTTP 404, got %s" % transcode.segment_missing_status(s, 0))
    s.failed = "enc failed"
    check(transcode.segment_missing_status(s, 0) == 500,
          "a real failed session still returns 500")
    s.failed = None
    # A miss at the playhead (not backward) is still a transcode failure.
    check(s._should_ignore_backward(47) is False, "seg 47 is not backward")
    check(transcode.segment_missing_status(s, 47) == 500,
          "a missing playhead segment is still HTTP 500")

print("HEVC remux stages are not empty")
with tempfile.TemporaryDirectory() as td:
    config.TRANSCODE_DIR = Path(td)
    s = transcode.Session("v269-remux", SHORT, "remux", 0, BOUNDS)
    check(s.hevc is True, "remux of an HEVC source is marked hevc")
    check(s.profile == "remux", "profile is remux")
    check(list(s.stages), "stages is non-empty, got %r" % list(s.stages))
    check(s.stage in s.stages, "stage property does not IndexError (got %r)" % (s.stage,))
    # Accessing the start() log fields must not raise.
    try:
        _ = (s.encoder, s.stage)
        check(True, "encoder and stage are readable on an HEVC remux session")
    except IndexError as e:
        check(False, "encoder/stage raised IndexError: %s" % e)

# Changelog / README mention the resume 500 and the remux stages bug
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
print("docs")
check(__version__ == "2.6.9" and "## 2.6.9" in ch and ch.find("## 2.6.9") < ch.find("## 2.6.8"),
      "CHANGELOG has 2.6.9 above 2.6.8")
sec = ch.split("## 2.6.9", 1)[1].split("## 2.6.8", 1)[0]
check("500" in sec and ("MEDIA-SEQUENCE" in sec or "start_seg" in sec or "playhead" in sec.lower()),
      "CHANGELOG describes the resume HTTP 500 / playlist start")
check("IndexError" in sec or "stages" in sec, "CHANGELOG describes the empty stages remux bug")
check("**2.6.9:**" in rd and rd.find("**2.6.9:**") < rd.find("**2.6.7:**"),
      "README 2.6.9 bullet is above 2.6.7")
for bad in ("192.168.", "password=", "ms_session=secret", "ADMIN_PASSWORD", "BEGIN RSA"):
    check(bad not in sec, "2.6.9 changelog does not contain %r" % bad)

if failed:
    print("FAILED", failed)
    sys.exit(1)
print("all 2.6.9 tests pass")
