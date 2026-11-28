"""2.6.2: Direct Play start hang — yield preload, start timeout, phone native=1."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v262-"))
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


from app.version import __version__
from app import db, preload

db.migrate()

appjs = (ROOT / "app/static/app.js").read_text()
srv = (ROOT / "app/server.py").read_text()
pl = (ROOT / "app/preload.py").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
ver = (ROOT / "app/version.py").read_text()

print("version and docs")
check(__version__ == "2.6.2", "version is 2.6.2")
check("## 2.6.2" in ch and ch.find("## 2.6.2") < ch.find("## 2.6.1"), "CHANGELOG has 2.6.2 above 2.6.1")
sec = ch.split("## 2.6.2", 1)[1].split("## 2.6.1", 1)[0]
check("Waiting for the first picture" in sec or "Direct Play" in sec,
      "CHANGELOG 2.6.2 describes the Direct Play start fix")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public docs use 192.0.2.10")
check("**2.6.2:**" in rd, "install README mentions 2.6.2")
rd262 = rd.split("**2.6.2:**", 1)[1].split("**2.6.1:**", 1)[0] if "**2.6.2:**" in rd else ""
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho", "192.168.111", "192.168.30"):
    check(bad not in sec and bad not in rd262, "2.6.2 docs do not name %s" % bad)

print("preload yields for Direct Play")
check("def note_direct_play" in pl, "preload.note_direct_play exists")
check("DIRECT_BUSY_S" in pl, "direct-play busy window is named")
check("preload.yield_to_playback(" in srv and "preload.note_direct_play()" in srv,
      "direct_file yields and notes Direct Play")
check(srv.find("def direct_file") < srv.find("preload.yield_to_playback(") or
      "def direct_file" in srv, "direct_file is present")
# yield happens in the direct_file body, before opening the file
df = srv.split("def direct_file", 1)[1].split("\n@", 1)[0]
check("yield_to_playback(" in df and "note_direct_play()" in df,
      "yield and note are inside direct_file")
check("note_direct_play()" in srv.split("def _range_response", 1)[1].split("def direct_file", 1)[0],
      "range reads refresh note_direct_play")

# busy() should see a recent note_direct_play even with no transcode session
preload._direct_until = 0.0
check(preload.busy() is False, "busy is false with no sessions and no direct play")
preload.note_direct_play()
check(preload.busy() is True, "note_direct_play makes busy() true")
# expire the window
preload._direct_until = time.time() - 1
check(preload.busy() is False, "busy is false after the direct-play window")

print("web player start timeout")
check("DIRECT_START_MS" in appjs and "12000" in appjs, "12s Direct Play start timeout")
check("function armStartWatch" in appjs and "function clearStartWatch" in appjs,
      "arm/clear start watch helpers")
check('fallback("no picture yet")' in appjs, "timeout falls back with no picture yet")
check("armStartWatch();" in appjs, "startStream arms the watch")
# 2.6.5: hideWait only clears the watch once videoWidth > 0; still must call it.
hwfn = appjs.split("function hideWait", 1)[1].split("function ", 1)[0]
check("clearStartWatch()" in hwfn, "hideWait talks to the start watch")
check("function teardownVideo" in appjs and "clearStartWatch();" in appjs,
      "teardown clears the start watch")

print("phone web player does not advertise native=1")
check("function usingNativePlayer" in appjs, "usingNativePlayer helper")
check("MSAndroid.isTv" in appjs, "usingNativePlayer checks the isTv bridge")
check("if (usingNativePlayer()) parts.push(\"native=1\")" in appjs,
      "capsQuery sends native=1 only when the native player is used")
check("nativePlaySupported() || n.native" not in appjs,
      "capsQuery no longer treats playNative-exists as native=1")
check("nativePlaySupported()) ? \"1\" : \"0\")" not in appjs.split("function capsQuery")[1].split("function qualityCapOn")[0],
      "mkv cap is not forced on just because playNative exists")
# 2.4 tests still look for the string native=1
check("native=1" in appjs and "hevc10=1" in appjs, "native=1 still present for the TV path")

if failed:
    print("FAILED", failed)
    sys.exit(1)
print("all passed")
