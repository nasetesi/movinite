"""2.4: native ExoPlayer caps, Direct Play of HEVC/HDR/surround, JS handoff. 2.3 / 2.1.4 kept."""
import hashlib, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v24-"))
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

appjs = (ROOT / "app/static/app.js").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
srv = (ROOT / "app/server.py").read_text()
trp = (ROOT / "app/transcode.py").read_text()
ver = (ROOT / "app/version.py").read_text()

from app.version import __version__
from app import db, transcode
from app.server import playback_info

db.migrate()

def film(w=3840, h=2160, codec="hevc", **extra):
    it = {"id": 1, "path": "/tmp/f.mkv", "width": w, "height": h, "vcodec": codec,
          "media_type": "video", "duration": 6000, "bitrate": 20000000, "mtime": 1.0,
          "container": "matroska,webm", "pix_fmt": "yuv420p10le",
          "audio_streams": "[]", "subtitle_streams": "[]", "external_subs": "[]",
          "acodec": "eac3", "color_transfer": "smpte2084"}
    it.update(extra)
    return it

print("source and docs")
check(__version__ == "2.4", "version is 2.4")
check("## 2.4" in ch and ch.find("## 2.4") < ch.find("## 2.3"), "CHANGELOG has 2.4 above 2.3")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")
check("2.4" in rd, "README mentions 2.4")

print("2.1.4 TV navigation is unchanged")
h = hashlib.sha256(tvjs.encode()).hexdigest()
check(h == "50943f125dd9ea89c21079f4859f1006672eab06297530d95e29a14b55ee4e39",
      "tv-plex.js is still the 2.1.4 file")
check("rail" in tvjs.lower() or "slide" in tvjs.lower() or "drawer" in tvjs, "tv-plex.js still has the rail / slide-out")

print("JS handoff and caps")
check("function nativePlaySupported" in appjs, "nativePlaySupported helper")
check("MSAndroid.playNative" in appjs, "Play hands off to playNative")
check("MSAndroid.decoderCaps" in appjs, "decoderCaps is read from the bridge")
check("native=1" in appjs and "hevc10=1" in appjs, "capsQuery sends native=1 and hevc10")
check("dts=1" in appjs and "truehd=1" in appjs, "capsQuery sends dts/truehd")
# 2.0.2 path: without playNative the in-page player still starts
check("fall through to the in-page player" in appjs or "2.0.2" in appjs, "web player remains a fallback")
check("startStream(mode, P.start)" in appjs, "web startStream is still used when there is no native player")

print("server native caps")
check("def client_caps_from_params" in trp, "client_caps_from_params")
check("def native_video_ok" in trp, "native_video_ok")
check("passthrough_audio" in srv, "playback reports passthrough_audio")
check("hdr_passthrough" in srv, "playback reports hdr_passthrough")
check("acopy" in trp and "acopy" in srv, "remux can copy AC3/EAC3")

# Browser / 2.0.2: 10-bit HEVC + EAC3 + HDR is not Direct Play
browser = playback_info(film())
check(browser["direct"] is False, "2.0.2 / browser: 10-bit HEVC HDR is not Direct Play")
check(browser.get("native") is False, "browser playback is not marked native")
check(browser["passthrough_audio"] == [], "browser has no passthrough list")

# Native TV with full caps: Direct Play
nat = transcode.client_caps_from_params({
    "native": "1", "hevc": "1", "hevc10": "1", "eac3": "1", "ac3": "1",
    "dts": "1", "truehd": "1", "hdr10": "1", "hlg": "1", "mkv": "1", "surr": "6",
})
pb = playback_info(film(), client=nat)
check(pb["direct"] is True, "native: 4K HEVC Main10 HDR10 + EAC3 MKV is Direct Play")
check(pb["native"] is True, "playback.native is true")
check(pb["hdr"] == "HDR10", "hdr is HDR10")
check(pb["hdr_passthrough"] is True, "HDR passthrough is offered")
check("eac3" in pb["passthrough_audio"], "EAC3 is in the passthrough list")

# Missing hevc10: not direct
no10 = transcode.client_caps_from_params({"native": "1", "hevc": "1", "eac3": "1", "hdr10": "1", "mkv": "1"})
pb2 = playback_info(film(), client=no10)
check(pb2["direct"] is False, "native without hevc10 does not Direct Play 10-bit HEVC")

# Missing eac3: not direct (TrueHD/DTS also off)
noa = transcode.client_caps_from_params({"native": "1", "hevc": "1", "hevc10": "1", "hdr10": "1", "mkv": "1"})
pb3 = playback_info(film(), client=noa)
check(pb3["direct"] is False, "native without EAC3 passthrough does not Direct Play EAC3")

# H.264 + AAC is still Direct Play in the browser (2.0.2 compatible)
h264 = film(w=1920, h=1080, codec="h264", pix_fmt="yuv420p", acodec="aac", color_transfer="", path="/tmp/f.mp4")
h264["container"] = "mov,mp4,m4a,3gp,3g2,mj2"
pb4 = playback_info(h264)
check(pb4["direct"] is True, "browser: H.264 8-bit AAC MP4 stays Direct Play")

# AC3 copy in remux when acopy=1
class Dummy:
    pass
from app.transcode import Session
# Don't construct a full session (needs item on disk); check the helper text and session_id.
s0 = transcode.session_id(1, "remux", 0, 1, "p", 0, 0, 0)
s1 = transcode.session_id(1, "remux", 0, 1, "p", 0, 0, 1)
check(s0 != s1, "acopy changes the transcode session id")

print("native player source is in the Android tree (checked by the APK build)")
print("done, failed =", failed)
sys.exit(1 if failed else 0)
