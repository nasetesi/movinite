"""1.7.9: faster first picture — 2s segments, caches, playlist kickoff.

    python3 tests/test_v179.py
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["MS_DATA_DIR"] = tempfile.mkdtemp(prefix="ms-v179-") + "/data"

from app.version import __version__  # noqa: E402
from app import db, preload, transcode  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def film(w=1920, h=1080, codec="h264", **extra):
    it = {"id": 1, "path": "/tmp/f.mkv", "width": w, "height": h, "vcodec": codec,
          "media_type": "video", "duration": 6000, "bitrate": 6300000, "mtime": 1.0,
          "container": "matroska,webm", "pix_fmt": "yuv420p", "audio_streams": "[]"}
    it.update(extra)
    return it


def main():
    vt = tuple(int(x) for x in __version__.split("."))
    check(vt >= (1, 7, 9), "version is 1.7.9 or later (%s)" % __version__)
    ver = (HERE.parent / "app/version.py").read_text()
    check("__version__" in ver, "version.py defines __version__")
    ch = (HERE.parent / "CHANGELOG.md").read_text()
    check("## 1.7.9" in ch and "2-second" in ch and "Opening-clip" in ch, "CHANGELOG has a 1.7.9 entry")
    js = (HERE.parent / "app/static/app.js").read_text()
    srv = (HERE.parent / "app/server.py").read_text()
    tc = (HERE.parent / "app/transcode.py").read_text()
    dbpy = (HERE.parent / "app/db.py").read_text()

    print("segments and pause window")
    check(transcode.SEG == 2.0, "SEG is 2 seconds")
    check(transcode.AHEAD_PAUSE_S == 150 and transcode.AHEAD_RESUME_S == 72,
          "pause / resume thresholds are 150s / 72s")
    check(transcode.RESTART_AHEAD_S == 60, "ffmpeg restarts only if the request is 60s ahead")
    check("RESTART_AHEAD_S" in tc and "(n - max(hi, self.start_seg)) * SEG" in tc,
          "restart threshold is in seconds, not a fixed +4 segments")
    check("ahead_s" in tc and "AHEAD_PAUSE_S" in tc, "housekeep pause is time-based")
    cmd_src = tc
    check('expr:gte(t,n_forced*%g)" % SEG' in cmd_src or "n_forced*%g" % transcode.SEG in cmd_src
          or "n_forced*%g" in cmd_src,
          "forced keyframes use SEG")

    print("schema 9")
    check(int(re.search(r"SCHEMA_VERSION = (\d+)", dbpy).group(1)) >= 9, "SCHEMA_VERSION is 9 or later")
    check("CREATE TABLE IF NOT EXISTS subtitle_cache" in dbpy, "subtitle_cache table")
    check("CREATE TABLE IF NOT EXISTS prefetch_cache" in dbpy, "prefetch_cache table")
    check('("items", "rotation"' in dbpy and '("items", "color_transfer"' in dbpy,
          "items gain rotation and color_transfer columns")
    check("_backup_db(c, 9)" in dbpy, "migrate snapshots the DB before schema 9")
    check("status='retry'" in dbpy, "old empty keyframe rows become retryable")

    db.migrate()
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] in ("9", "10", "11"),
          "fresh install is schema 9 or later")
    check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='subtitle_cache'"),
          "subtitle_cache exists")
    check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='prefetch_cache'"),
          "prefetch_cache exists")
    # simulate schema 8 -> 9 backup
    data = Path(os.environ["MS_DATA_DIR"])
    with db.tx() as c:
        c.execute("UPDATE meta SET value='8' WHERE key='schema_version'")
    db.migrate()
    bak = data / "media-server.db.pre-schema9"
    check(bak.is_file(), "schema 8 -> 9 writes media-server.db.pre-schema9")
    check(oct(bak.stat().st_mode & 0o777) == "0o600", "pre-schema9 mode is 600 (got %s)" % oct(bak.stat().st_mode & 0o777))
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] in ("9", "10", "11"),
          "migrate stamps schema 9 or later")

    print("playlist / kickoff / remux cache")
    it = film()
    pl = transcode.playlist(it)
    check("#EXTINF:2.000," in pl or "#EXT-X-TARGETDURATION:2" in pl, "playlist uses 2s segments")
    check(pl.count("#EXTINF:") == 3000, "6000s film is 3000 two-second segments")
    check("def kickoff" in tc and "transcode.kickoff" in srv, "playlist request starts ffmpeg")
    check("Cache-Control\": \"no-store" in srv or "no-store, no-cache" in srv,
          "HLS responses are uncached")

    # remux_bounds must not probe on the play path
    miss = transcode.remux_bounds(film(codec="hevc"), probe=False)
    check(miss is None, "play path does not probe remux bounds")
    # a stored retry/null is not a permanent ban
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO libraries(id,name,kind,path,scan_interval_h,created_at) "
                  "VALUES(1,'Movies','movies','/tmp',6,1)")
        c.execute("INSERT OR REPLACE INTO items(id, library_id, path, media_type, kind, title, added_at, probed, mtime, duration, container, vcodec, pix_fmt) "
                  "VALUES(42,1,'/tmp/x.mkv','video','movie','X',1,1,1.0,6000,'matroska,webm','h264','yuv420p')")
        c.execute("INSERT OR REPLACE INTO keyframes(item_id, mtime, data, status, checked_at, attempts) "
                  "VALUES(42,1.0,NULL,'retry',1,1)")
    row = film()
    row["id"] = 42
    check(transcode.remux_bounds(row, probe=False) is None, "retry status is a miss, not a stored failure plan")

    print("cached probes")
    hdr = transcode.hdr_info(film(pix_fmt="yuv420p10le", color_transfer="smpte2084"))
    check(hdr == "HDR10", "hdr_info uses scanned color_transfer (HDR10)")
    check(transcode.hdr_info(film(pix_fmt="yuv420p10le", color_transfer="arib-std-b67")) == "HLG",
          "hdr_info recognises HLG")
    from app import hwaccel
    check(hwaccel.rotation({"rotation": 90, "path": "/no/such"}) == 90,
          "rotation uses the scanned item field and skips ffprobe")
    check("color_transfer" in (HERE.parent / "app/media.py").read_text()
          and "side_data_list" in (HERE.parent / "app/media.py").read_text(),
          "library scan records rotation and color_transfer")

    print("preload cache")
    check(preload.cache_gb() == 2.0, "default opening-clip cache is 2 GB")
    preload.set_cache_gb(3)
    check(preload.cache_gb() == 3.0, "cache size setting sticks")
    preload.set_cache_gb(2)
    s = transcode.Session("pf-test", film(id=42), "1080p", 0)
    # plant a ready opening clip
    src = preload.prefetch_dir(42, "start", 0.0)
    src.mkdir(parents=True, exist_ok=True)
    for n in range(3):
        (src / ("seg%d.ts" % n)).write_bytes(b"x" * 2000)
    rel = str(src.relative_to(Path(os.environ["MS_DATA_DIR"])))
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO prefetch_cache(item_id, kind, start_t, mtime, profile, dir, size, last_access, status, checked_at) "
                  "VALUES(42,'start',0,1.0,'1080p',?,?,?,'ready',1)",
                  (rel, 6000, 1))
    n = preload.apply_to_session(s, 0)
    check(n == 3, "apply_to_session copies three cached opening segments")
    check(s._ready(0) and s._ready(1) and s._ready(2), "copied segments are ready in the session dir")
    # kickoff should start after the cached tip (we won't actually spawn ffmpeg: stub start)
    started = []
    s.start = lambda seg: started.append(seg)
    transcode.kickoff(s, 0)
    check(started == [3], "kickoff starts ffmpeg after the cached opening clips (seg 3)")

    print("client / SW / settings")
    check("try { probeDecoders(); }" in js and "await probeDecoders()" not in js,
          "play does not wait for the decoder probe")
    check("opts.item && opts.item.id === id" in js and "item: it" in js,
          "play from the details page reuses the loaded item")
    check("it.playback && it.playback.seg" in js and "&start=${Math.floor" in js,
          "every HLS playlist request includes the start segment")
    check("function fetchVtt" in js and "r.status === 202" in js, "client retries 202 subtitle responses")
    check("Opening-clip cache" in js and "prefetch_cache_gb" in js and "prefetch_cache_gb" in srv,
          "Settings → Transcoding has the opening-clip cache size")
    check("status_code=202" in srv and "sub_enqueue" in srv, "uncached subtitles return 202 and enqueue")
    check("ASSETS=" in srv and "caches.open" in srv and "caches.match" in srv,
          "service worker precaches versioned assets")
    check("u.pathname.startsWith('/api/')" in srv, "service worker never caches API or HLS")
    check("png, .svg, .ico" in srv or ".png" in srv and "max-age=31536000" in srv,
          "versioned static assets get long cache headers")
    upd = (HERE.parent / "update.sh").read_text()
    inst = (HERE.parent / "install.sh").read_text()
    check("data/prefetch" in upd and "data/subs" in upd and "pre-schema9" in upd,
          "update.sh creates cache dirs and mentions the schema 9 backup")
    check("data/prefetch" in inst and "data/subs" in inst, "install.sh creates cache dirs")

    shutil.rmtree(s.dir, ignore_errors=True)
    if fails:
        print("\n%d FAILED" % len(fails))
        for f in fails:
            print("  -", f)
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
