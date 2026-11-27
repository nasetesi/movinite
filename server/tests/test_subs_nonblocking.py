"""fix/transcode-stuck: subtitle requests never hold up playback.

Field report (Nov 27): on the Android TV some 4K movies sat on "Transcode 1080p" forever
(Heart Of The Beast: 44 SRT tracks; One Last Shot: 28; Warfare and The Karate Kid (1984):
one 4.6 GB file read per track took longer than the old 180 s timeout). The native player
requests every text track when it starts and waits for all of them; the server ran one
full-file ffmpeg per request. This test uses a fake 'slow NAS' ffmpeg wrapper and checks:

  * every subtitle request answers in ~2 s with a valid (empty) WebVTT and 202
  * all embedded tracks of a title are extracted by ONE ffmpeg pass, started once
  * other requests (health, HLS-style work) are not starved while the pass runs
  * once the pass is done every track is served with 200 and real cues
  * a failed pass is not re-run on every play (cooldown), and a sidecar still works

    python3 tests/test_subs_nonblocking.py
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = Path(tempfile.mkdtemp(prefix="ms-subs-"))
os.environ["MS_DATA_DIR"] = str(TMP / "data")
REAL_FFMPEG = os.environ.get("FFMPEG") or "ffmpeg"
SLOW_S = 6
CALLS = TMP / "ffmpeg-sub-calls.log"
WRAP = TMP / "slow-ffmpeg.sh"
WRAP.write_text("""#!/bin/sh
# fake slow NAS: reading an embedded track out of the big file takes %d s; log each one
case "$*" in
  *webvtt*) echo "$*" >> "%s" ;;
esac
case "$*" in
  *"-map 0:"*webvtt*) sleep %d ;;
esac
exec %s "$@"
""" % (SLOW_S, CALLS, SLOW_S, REAL_FFMPEG))
WRAP.chmod(WRAP.stat().st_mode | stat.S_IEXEC)
os.environ["MS_FFMPEG"] = str(WRAP)

from app import auth, db, media, preload, server, settings  # noqa: E402

fails = []
NTRACKS = 12
PORT = 8262


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def build_media():
    media_dir = TMP / "media"
    media_dir.mkdir(parents=True)
    srt_inputs, maps, meta = [], [], []
    for i in range(NTRACKS):
        f = media_dir / ("t%02d.srt" % i)
        f.write_text("1\n00:00:00,500 --> 00:00:03,000\nTrack %d line one\n\n"
                     "2\n00:00:03,500 --> 00:00:05,500\nTrack %d line two\n" % (i, i), encoding="utf-8")
        srt_inputs += ["-f", "srt", "-i", str(f)]
        maps += ["-map", "%d:0" % (i + 2)]
        meta += ["-metadata:s:s:%d" % i, "language=eng"]
    mkv = media_dir / "Heart Test (2026) [2160p].mkv"
    cmd = [REAL_FFMPEG, "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=0x202030:s=640x360:d=6:r=24",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=6"] + srt_inputs + \
          ["-map", "0:v", "-map", "1:a"] + maps + meta + \
          ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "srt", "-t", "6", str(mkv)]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    check(p.returncode == 0 and mkv.is_file(), "built a sample MKV with %d SRT tracks" % NTRACKS)
    side = media_dir / "Heart Test (2026) [2160p].en.srt"
    side.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello from the sidecar\n", encoding="utf-8")
    for f in media_dir.glob("t*.srt"):
        f.unlink()
    return media_dir, mkv


def main():
    print("source checks")
    srv = (HERE.parent / "app/server.py").read_text()
    js = (HERE.parent / "app/static/app.js").read_text()
    body = srv[srv.index('def subtitles(item_id'):srv.index("# settings + TMDB")]
    check("preload.extract_sub(it, key)\n" not in body and "ensure_subs_async" in body,
          "the subtitle endpoint no longer extracts embedded tracks inside the request")
    check("preload.EMPTY_VTT" in body and "status_code=202" in body, "an uncached track answers 202 with a valid empty WebVTT")
    check(preload.EMPTY_VTT.startswith(b"WEBVTT"), "EMPTY_VTT is valid WebVTT")
    check("i < 90" in js and "Math.min(5000" in js, "web player keeps retrying 202 for a long pass (~6 min, 5 s cap)")
    cmd, outs = preload.one_pass_cmd({"path": "/x.mkv"}, ["s2", "s3", "s9"], "/tmp/o")
    check(cmd.count("-i") == 1 and cmd.count("-map") == 3 and len(outs) == 3,
          "one_pass_cmd reads the file once and writes one WebVTT per track")

    media_dir, mkv = build_media()
    raw = media.ffprobe(str(mkv))
    info = media.summarize_probe(raw)
    subs = json.loads(info.get("subtitle_streams") or "[]")
    check(len([s for s in subs if s.get("text")]) == NTRACKS, "all %d text tracks are probed" % NTRACKS)
    found = media.find_external_subs(mkv)

    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    settings.put("hw_transcode", "off")
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies',?,0,?)",
                  (str(media_dir), now))
        c.execute(
            "INSERT INTO items(library_id,path,media_type,kind,title,sort_title,year,file_title,"
            "duration,container,vcodec,width,height,size,mtime,added_at,probed,"
            "audio_streams,subtitle_streams,external_subs,meta_status) "
            "VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(mkv), "video", "movie", "Heart Test", "heart test", 2026, "Heart Test",
             6, "mkv", "h264", 640, 360, mkv.stat().st_size, now, now, 1,
             info.get("audio_streams"), info.get("subtitle_streams"), json.dumps(found), "unmatched"))
    item = db.row("SELECT * FROM items")
    pb = server.playback_info(item)
    keys = [s["key"] for s in pb["subtitles"] if s.get("kind") != "image"]
    emb = [k for k in keys if k.startswith("s")]
    check(len(emb) == NTRACKS and any(k.startswith("e") for k in keys), "playback lists %d embedded + sidecar tracks" % NTRACKS)

    import uvicorn
    threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                     daemon=True).start()
    for _ in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/health" % PORT, timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)

    def call(path, method="GET", data=None, cookie=None, timeout=30, ua="Movinite-Android/2.4.4"):
        headers = {"Accept": "*/*", "User-Agent": ua}
        if cookie:
            headers["Cookie"] = cookie
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read(), r.headers.get("Set-Cookie") or ""
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read(), ""

    st, _, _, setc = call("/api/login", "POST", {"username": "admin", "password": "TestPass14!"})
    cookie = setc.split(";", 1)[0]
    check(st == 200 and cookie, "fake admin login")
    iid = item["id"]

    print("TV start: every text track requested at once (like ExoPlayer)")
    CALLS.write_text("")
    t0 = time.time()

    def get(k):
        s = time.time()
        r = call("/api/items/%d/subs/%s.vtt" % (iid, k), cookie=cookie, timeout=30)
        return k, r[0], r[1], r[2], time.time() - s

    with ThreadPoolExecutor(max_workers=len(keys) + 4) as ex:
        futs = [ex.submit(get, k) for k in keys]
        # while those are in flight, the server must still answer other requests
        time.sleep(0.3)
        hs = time.time()
        hst = call("/api/health", timeout=10)[0]
        health_s = time.time() - hs
        res = [f.result() for f in futs]
    slow = max(r[4] for r in res)
    check(hst == 200 and health_s < 1.5, "health answers during the burst (%.2fs)" % health_s)
    check(slow < 3.5, "every subtitle request answered within 3.5 s (slowest %.2fs; fake NAS pass is %ds)" % (slow, SLOW_S))
    pend = [r for r in res if r[0].startswith("s")]
    check(all(r[1] == 202 and r[3].startswith(b"WEBVTT") for r in pend),
          "uncached embedded tracks get 202 + a valid empty WebVTT: %s" % sorted({r[1] for r in pend}))
    check(all("no-store" in (r[2].get("cache-control") or r[2].get("Cache-Control") or "") for r in pend),
          "the placeholder is not cached by the player")
    side = [r for r in res if r[0].startswith("e")]
    check(side and all(r[1] == 200 and b"sidecar" in r[3] for r in side), "the sidecar track is served at once with its cues")

    # wait for the background pass
    for _ in range(int(SLOW_S * 10 + 100)):
        if not preload.subs_inflight(iid):
            break
        time.sleep(0.1)
    lines = [ln for ln in CALLS.read_text().splitlines() if ln.strip()]
    emb_calls = [ln for ln in lines if " -map 0:" in ln]
    check(len(emb_calls) == 1, "exactly one ffmpeg pass for all embedded tracks (got %d)" % len(emb_calls))
    check(emb_calls and all(("-map 0:%s " % k[1:]) in emb_calls[0] for k in emb),
          "that one pass writes all %d tracks" % NTRACKS)
    check(time.time() - t0 < SLOW_S + 8, "the pass finished in the background (%.1fs)" % (time.time() - t0))

    print("next request after the pass: real cues")
    ok = 0
    for k in emb:
        st, hd, body, _ = call("/api/items/%d/subs/%s.vtt" % (iid, k), cookie=cookie)
        n = int(k[1:]) - 2
        if st == 200 and body.startswith(b"WEBVTT") and ("Track %d line one" % n).encode() in body:
            ok += 1
    check(ok == NTRACKS, "all %d tracks now return 200 with their own cues (%d)" % (NTRACKS, ok))
    check(not preload.missing_sub_keys(item), "nothing left to extract for the title")

    print("a second burst does not start another pass")
    CALLS.write_text("")
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(get, keys))
    check(CALLS.read_text().strip() == "", "cached tracks are served without running ffmpeg")

    print("failure handling")
    bad = dict(item)
    bad["id"] = item["id"]
    with db.tx() as c:
        c.execute("DELETE FROM subtitle_cache WHERE item_id=?", (iid,))
        c.execute("UPDATE items SET path=? WHERE id=?", (str(media_dir / "missing.mkv"), iid))
    bad = db.row("SELECT * FROM items WHERE id=?", (iid,))
    done = preload.extract_item_subs(bad, None, timeout=30, yieldable=False)
    check(not [k for k in done if k.startswith("s")], "a pass over an unreadable file caches no embedded track (%s)" % sorted(done))
    rows = db.rows("SELECT status FROM subtitle_cache WHERE item_id=? AND key LIKE 's%'", (iid,))
    check(rows and all(r["status"] == "retry" for r in rows), "its tracks are marked retry")
    check(preload.ensure_subs_async(bad) is False, "a just-failed title is not re-run on every play (cooldown)")
    st, _, body, _ = call("/api/items/%d/subs/%s.vtt" % (iid, emb[0]), cookie=cookie)
    check(st == 202 and body.startswith(b"WEBVTT"), "the player still gets an instant empty WebVTT")

    print("timeout is long enough for a 4K remux on the share")
    check(preload.SUB_PASS_TIMEOUT_S >= 900, "one-pass timeout is %ds (measured 187 s for a 4.6 GB file)" % preload.SUB_PASS_TIMEOUT_S)


if __name__ == "__main__":
    main()
    print("FAILS: %d" % len(fails) if fails else "ALL OK")
    raise SystemExit(1 if fails else 0)
