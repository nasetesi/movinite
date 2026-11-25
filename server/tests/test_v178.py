"""1.7.8: cap quality to the device; fix transcode pause after old segments are deleted.

    python3 tests/test_v178.py
"""
import os, signal, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["MS_DATA_DIR"] = tempfile.mkdtemp(prefix="ms-v178-") + "/data"

from app.version import __version__  # noqa: E402
from app import db, transcode  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def proc_state(pid):
    try:
        st = Path("/proc/%d/stat" % pid).read_text()
        # comm can contain spaces in parentheses; state is the field after the last ')'
        return st[st.rfind(")") + 2:].split()[0]
    except OSError:
        return "?"


def film(w, h, codec="hevc"):
    return {"id": 1, "path": "/tmp/f.mkv", "width": w, "height": h, "vcodec": codec,
            "media_type": "video", "duration": 6000, "bitrate": 6300000}


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 8), "version is 1.7.8 or later")
    ver = (HERE.parent / "app/version.py").read_text()
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 8), "version.py is 1.7.8 or later")
    ch = (HERE.parent / "CHANGELOG.md").read_text()
    check("## 1.7.8" in ch and "capped" in ch.lower() and "highest_done" in ch, "CHANGELOG has a 1.7.8 entry")
    js = (HERE.parent / "app/static/app.js").read_text()
    css = (HERE.parent / "app/static/style.css").read_text()
    srv = (HERE.parent / "app/server.py").read_text()
    tc = (HERE.parent / "app/transcode.py").read_text()

    check("function displayLongPx" in js and "devicePixelRatio" in js, "client reports screen × devicePixelRatio")
    check("mediaCapabilities" in js and "decodingInfo" in js, "client probes MediaCapabilities decodingInfo")
    check("MSAndroid.decoderCaps" in js, "client uses a MediaCodec JS bridge only if the app exposes one")
    check("qualityCap" in js and "Cap quality to this screen" in js, "Settings has a per-device cap override")
    check("Auto-capped to" in js and "pl-ss-cap" in js and "pl-ss-cap" in css,
          "quality menu / stats show Auto-capped to …")
    check("capQuery" in js and "disp=" in js and "nocap=1" in js, "playlist and item requests send disp / dec / nocap")
    check("device_cap" in srv and "clamp_profile" in srv, "item detail and HLS clamp to the device cap")
    check(__import__("app.db", fromlist=["SCHEMA_VERSION"]).SCHEMA_VERSION >= 8,
          "schema is 8 or later (1.7.8 cap needed no bump; 1.7.9 adds start-cache tables)")

    # --- quality cap ---
    check(transcode.device_cap_base(1920) == "1080p", "1920x1200 tablet (longer side 1920) caps at 1080p")
    check(transcode.device_cap_base(1918) == "1080p", "1918 px still caps at 1080p (slack)")
    check(transcode.device_cap_base(1280) == "720p", "1280 px caps at 720p")
    check(transcode.device_cap_base(2560) == "1440p", "2560 px caps at 1440p")
    check(transcode.device_cap_base(3120) == "1440p", "S24 Ultra-class 3120 px caps at 1440p (below 4K box)")
    check(transcode.device_cap_base(3840) == "2160p", "3840 px allows 4K")
    check(transcode.device_cap_base(1920, 3840) == "1080p", "display 1920 and decoder 4K still caps at 1080p")
    check(transcode.device_cap_base(3840, 1920) == "1080p", "4K screen but decoder limited to 1080p caps at 1080p")
    check(transcode.device_cap_base(0, 0) is None, "no display or decoder report means no cap")

    big = film(3840, 1918)
    small = film(1920, 1080)
    check(not transcode.source_fits_cap(big, "1080p"), "4K source does not fit a 1080p cap (no remux/direct)")
    check(transcode.source_fits_cap(small, "1080p"), "1080p source fits a 1080p cap")
    check(transcode.source_fits_cap(big, "2160p"), "4K source fits a 4K cap")

    p, cap, chg = transcode.clamp_profile("2160p.hevc", big, 1920)
    check(p == "1080p" and cap == "1080p" and chg, "saved 4K HEVC is clamped to 1080p on a 1920 px tablet")
    p, cap, chg = transcode.clamp_profile("1080p", big, 1920)
    check(p == "1080p" and not chg, "1080p is left alone when it already fits the cap")
    p, cap, chg = transcode.clamp_profile("remux", big, 1920)
    check(p is None and cap == "1080p" and chg, "remux of a 4K file is refused on a 1080p cap")
    p, cap, chg = transcode.clamp_profile("direct", big, 1920)
    check(p is None and chg, "direct play of a 4K file is refused on a 1080p cap")
    p, cap, chg = transcode.clamp_profile("remux", small, 1920)
    check(p == "remux" and not chg, "remux of a 1080p file is allowed on a 1080p cap")
    p, cap, chg = transcode.clamp_profile("2160p.hevc", big, 1920, nocap=True)
    check(p == "2160p.hevc" and cap is None and not chg, "nocap override leaves 4K alone")
    p, cap, chg = transcode.clamp_profile("1440p.hevc", big, 2560)
    check(p == "1440p.hevc" and not chg, "2K HEVC is kept when the cap is 1440p")

    # --- highest_done + AHEAD_PAUSE after old segments are deleted ---
    db.migrate()
    s = transcode.Session("pause-test", film(1920, 1080, "h264"), "1080p", 0)
    s.start_seg = 7
    s.last_req = 96
    # Live-test shape: start_seg 7 is gone, remaining run is 56..306
    for n in range(56, 307):
        (s.dir / ("seg%d.ts" % n)).write_bytes(b"x")
    check(s.highest_done() == 306,
          "highest_done is 306 after segs 7-55 were deleted (not -1)")
    check(s.highest_done() - s.last_req > transcode.AHEAD_PAUSE,
          "session is far enough ahead that housekeep should pause")

    proc = subprocess.Popen(["sleep", "90"], preexec_fn=os.setsid)
    s.proc = proc
    s.paused = False
    try:
        s.housekeep()
        time.sleep(0.05)
        check(s.paused, "housekeep pauses ffmpeg when far ahead after a gap at start_seg")
        check(proc_state(proc.pid) == "T", "ffmpeg process group is actually SIGSTOP'd (state T)")

        # Re-fetching an already-ready segment must not resume the paused encoder
        got = s.get_segment(96, timeout=1)
        check(got is not None and got.exists(), "get_segment returns a ready segment")
        check(s.paused and proc_state(proc.pid) == "T",
              "get_segment of a ready segment does not SIGCONT a paused ffmpeg")

        # A request past the produced tip should resume so ffmpeg can catch up
        s.last_req = 306
        s._resume_if_needed()
        time.sleep(0.05)
        check(not s.paused, "resume when the player catches up")
        check(proc_state(proc.pid) in ("S", "R", "D"), "process is running again after resume")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGCONT)
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Ready-path must not call _resume_if_needed: also asserted in source
    check("A ready segment must not SIGCONT" in tc, "get_segment comments the ready-path resume fix")
    check("now-missing first segment" in ch or "start_seg" in ch, "changelog explains the pause bug")

    if fails:
        print("\n%d FAILED" % len(fails))
        for f in fails:
            print("  -", f)
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
