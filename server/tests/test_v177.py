"""1.7.7: fully-hardware 4K transcode path, sticky per-stream fallback.

    python3 tests/test_v177.py
"""
import os, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["MS_DATA_DIR"] = tempfile.mkdtemp(prefix="ms-v177-") + "/data"

from app.version import __version__  # noqa: E402
from app import hwaccel, transcode  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 7), "version is 1.7.7 or later")
    ver = (HERE.parent / "app/version.py").read_text()
    check('__version__ = "1.7.7"' in ver, "version.py is 1.7.7")
    ch = (HERE.parent / "CHANGELOG.md").read_text()
    check("## 1.7.7" in ch and "extra_hw_frames" in ch and "sticky" in ch.lower(), "CHANGELOG has a 1.7.7 entry")
    js = (HERE.parent / "app/static/app.js").read_text()
    html = (HERE.parent / "app/static/index.html").read_text() if (HERE.parent / "app/static/index.html").exists() else ""

    pre, vf, enc = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000)
    check("-hwaccel_output_format" in pre and pre[pre.index("-extra_hw_frames") + 1] == "64",
          "full VAAPI path keeps frames on the GPU and reserves 64 extra surfaces")
    check(enc[enc.index("-low_power") + 1] == "1" and enc[1] == "h264_vaapi",
          "H.264 encode uses the low-power / VDENC entry")
    check(vf == "scale_vaapi=w=-2:h=1080:format=nv12", "SDR scale is scale_vaapi to nv12")

    hwaccel._filters = {"tonemap_vaapi", "scale_vaapi"}
    _, vfh, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, hdr="HDR10")
    check("tonemap_vaapi" in vfh and "p010" in vfh, "HDR uses tonemap_vaapi on the GPU")
    hwaccel._filters = set()
    _, vfm, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, hdr="HDR10")
    check("tonemap_vaapi" not in vfm and "scale_vaapi" in vfm, "HDR falls back to scale_vaapi if the filter is missing")
    hwaccel._filters = None

    _, _, qenc = hwaccel.stage_args("qsv", "/dev/dri/renderD128", "full", 720, 4000)
    check("-low_power" in qenc, "QSV encode also sets low_power")

    src = (HERE.parent / "app/transcode.py").read_text()
    check("remember_stage" in src and "apply_sticky" in src and "STICKY_S" in src,
          "fallback is remembered per stream")
    check("died_empty" in src and "staying on" in src,
          "a dead ffmpeg with no segment falls forward instead of relaunching the same stage")
    check("hdr=hdr_info(it)" in src, "the transcode command passes HDR info to stage_args")

    # sticky helpers
    transcode._sticky.clear()
    transcode.remember_stage("abc123", "enc", "ffmpeg exited", failed="full")
    class S:
        sid = "abc123"
        stages = ["full", "enc", "cpu"]
        stage_i = 0
        fallbacks = []
        @property
        def stage(self):
            return self.stages[self.stage_i]
    s = S()
    transcode.apply_sticky(s)
    check(s.stage == "enc" and s.fallbacks and s.fallbacks[-1].get("sticky"),
          "a recreated session resumes at the sticky stage with a logged reason")

    # global hold must be gone: enc failure still leaves the card active
    # (cannot call save() without a device; just assert active() no longer reads a hold
    #  and note_failure does not populate _failed)
    hwaccel._failed.clear()
    hwaccel.note_failure("vaapi", "/dev/dri/renderD128", "enc", "boom")
    check(("vaapi", "/dev/dri/renderD128") not in hwaccel._failed,
          "note_failure does not globally hold the card")

    check("MAX_TRANSCODES" in (HERE.parent / "app/config.py").read_text()
          and "MS_MAX_TRANSCODES" in (HERE.parent / "app/config.py").read_text(),
          "cap is configurable via MS_MAX_TRANSCODES")
    check(transcode.max_transcodes() == 4, "default transcode cap is 4")
    check("HW_RETRY_MAX" in src and "_handle_not_running" in src and "_journal_ffmpeg" in src,
          "one hardware retry, then sticky fallback, and ffmpeg stderr is journaled")
    check('"-loglevel", "warning"' in src and "LOG_TAIL_N" in src,
          "ffmpeg loglevel is warning and the last 50 log lines are kept")
    check("destroy(\"idle\")" in src and "client_close" in src and 'destroy("replaced")' in src
          and 'destroy("cap")' in src,
          "session destroy reasons are logged")
    check("note_client" in src and "normalize_player" in src,
          "player id and advertised caps are recorded")

    check("playerId" in js and "capsQuery" in js and "canRemux" in js,
          "the player sends a device id and codec capabilities")
    check("saved 2K/4K transcode no longer" in js or "prefer direct play or remux" in js.lower()
          or "canRemux(pb)" in js,
          "auto quality prefers remux/direct over a saved 4K transcode")
    check("hw-max" in js and "max_transcodes" in js, "Settings can change the transcode cap")
    check("stop?player=" in js, "closing the player stops only that device's session")

    hevc_it = {"id": 1, "path": "/tmp/x.mkv", "media_type": "video", "vcodec": "hevc",
               "pix_fmt": "yuv420p10le", "container": "matroska,webm", "duration": 120,
               "width": 3840, "height": 2160, "bitrate": 20000000, "audio_streams": "[]"}
    h264_it = dict(hevc_it, vcodec="h264", pix_fmt="yuv420p")
    av1_it = dict(hevc_it, vcodec="av1")
    check(transcode.remux_codec(hevc_it) == "hevc" and transcode.remux_eligible(hevc_it),
          "HEVC 10-bit MKV is remux-eligible")
    check(transcode.remux_codec(h264_it) == "h264", "H.264 8-bit MKV is still remux-eligible")
    check(not transcode.remux_eligible(av1_it), "AV1 is not remuxed")

    hs = transcode.Session("sidhevc", hevc_it, "remux", 0, bounds=[0.0, 6.0, 12.0])
    hcmd = hs._remux_cmd(0)
    check("-c:v" in hcmd and "copy" in hcmd and "fmp4" in hcmd and "hvc1" in hcmd,
          "HEVC remux copies the video into fMP4 with hvc1")
    check(hs.hevc and hs.ext == "m4s", "HEVC remux uses fMP4 segments")
    hs.destroy("error")

    h264s = transcode.Session("sidh264", h264_it, "remux", 0, bounds=[0.0, 6.0, 12.0])
    c264 = h264s._remux_cmd(0)
    check("mpegts" in c264 and "hvc1" not in c264, "H.264 remux still uses MPEG-TS")
    h264s.destroy("error")

    from app import db, settings
    db.migrate()
    transcode._sessions.clear()
    a = transcode.get_session(h264_it, "1080p", 0, 7, "playerAAA123")
    b = transcode.get_session(dict(h264_it, id=2), "1080p", 0, 7, "playerBBB123")
    check(a.sid != b.sid and len(transcode._sessions) == 2,
          "the same login on two devices gets two sessions")
    c = transcode.get_session(dict(h264_it, id=3), "720p", 0, 7, "playerAAA123")
    check(a.sid not in transcode._sessions and b.sid in transcode._sessions and c.sid in transcode._sessions,
          "switching title on one device replaces only that device's session")

    settings.put("max_transcodes", "1")
    check(transcode.max_transcodes() == 1, "the cap can be lowered in settings")
    transcode._sessions.clear()
    first = transcode.get_session(dict(h264_it, id=4), "1080p", 0, 1, "devOne")
    first.last_access = 0  # oldest
    second = transcode.get_session(dict(h264_it, id=5), "1080p", 0, 2, "devTwo")
    check(first.sid not in transcode._sessions and second.sid in transcode._sessions and len(transcode._sessions) == 1,
          "hitting the cap evicts the oldest session")
    settings.put("max_transcodes", "4")
    transcode._sessions.clear()

    check(transcode.normalize_player("ok_ID-123") == "ok_ID-123", "player id keeps letters, digits, dash, underscore")
    check(transcode.normalize_player("bad id!;/") == "badid", "player id strips unsafe characters")

    if fails:
        print("FAILED:", *fails, sep="\n  ")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
