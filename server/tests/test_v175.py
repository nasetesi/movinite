"""1.7.5: pinch-to-zoom / fit-fill, prompt captions that survive seek and quality changes,
transparent caption style, and a glass 2x2 server-stats panel (GPU badge stays purple).

    python3 tests/test_v175.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-v175-")
os.environ["MS_DATA_DIR"] = TMP + "/data"

from app import auth, db, media, server, settings  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 5), "version is 1.7.5 or later")
    check((HERE.parent / "install.sh").is_file() and (HERE.parent / "update.sh").is_file(),
          "install.sh and update.sh are still in the tree")
    js = (HERE.parent / "app/static/app.js").read_text()
    css = (HERE.parent / "app/static/style.css").read_text()
    html = (HERE.parent / "app/static/index.html").read_text()
    ver = (HERE.parent / "app/version.py").read_text()
    srv = (HERE.parent / "app/server.py").read_text()

    print("version / cache-busting")
    check(tuple(int(x) for x in __import__("re").search(r'__version__ = "([0-9.]+)"', ver).group(1).split(".")) >= (1, 7, 5), "version.py is 1.7.5 or later")
    html_resp = server._index_response()
    body = html_resp.body.decode()
    check(('app.js?v=%s"' % __version__) in body and ('style.css?v=%s"' % __version__) in body,
          "HTML stamps assets with ?v=%s" % __version__)
    check('serviceWorker.register("/sw.js?v=%s")' % __version__ in body,
          "service worker registered with ?v=%s" % __version__)
    sw = server.service_worker()
    swb = sw.body.decode() if not isinstance(sw.body, str) else sw.body
    if isinstance(swb, bytes):
        swb = swb.decode()
    check("const V='%s'" % __version__ in swb or 'const V="%s"' % __version__ in swb,
          "sw.js carries the running version")

    print("pinch / fit-fill")
    check("function setVideoFit(" in js and "function videoFit(" in js
          and 'localStorage.getItem("pl-videofit")' in js,
          "fit/fill is remembered per device in localStorage")
    check('setVideoFit("fill")' in js and 'setVideoFit("fit")' in js
          and "pinchDist" in js and "e.touches.length === 2" in js,
          "pinch out fills, pinch in fits")
    check(".pl-tap{" in css and "touch-action:none" in css[css.index(".pl-tap{"):css.index(".pl-tap{") + 220],
          ".pl-tap uses touch-action:none so the WebView delivers pinch gestures")
    check("touch-action:manipulation" not in css[css.index(".pl-tap{"):css.index(".pl-tap{") + 220],
          ".pl-tap no longer uses touch-action:manipulation (that blocks pinch)")
    check(".player video{" in css and "object-fit:contain" in css[css.index(".player video{"):css.index(".player video{") + 200],
          "default picture is object-fit:contain")
    check(".player.fit-fill video{object-fit:cover}" in css, "fill uses object-fit:cover")
    check("html.pl-pseudo-fs #player.fit-fill video{object-fit:cover}" in css,
          "fill also applies in CSS (pseudo) full screen")
    check('item("Fit (whole picture)"' in js and 'item("Fill (cover the screen)"' in js,
          "Fit / Fill is in the Quality / settings menu")

    print("captions")
    check('id="pl-cues"' in html and "function paintCues(" in js and "function parseVtt(" in js
          and "function addSubTrack(" in js,
          "custom cue overlay + VTT parser + addSubTrack")
    check("credentials: \"same-origin\"" in js and "SUB.cache" in js and "prefetchSubs(" in js,
          "VTT is fetched with cookies and cached, and prefetched at play start")
    check("Hls.Events.MEDIA_ATTACHED" in js and "Hls.Events.MANIFEST_PARSED" in js
          and 'addSubTrack($("#pl-subs").value, { keep: true })' in js,
          "captions are re-applied after an HLS src / quality change")
    check('["timeupdate", "seeked", "seeking", "loadedmetadata"].forEach(ev => video.addEventListener(ev, paintCues))' in js,
          "cues are repainted on seek and timeupdate")
    check("Loading subtitles" in js, "a loading hint shows until the first VTT is ready")
    check("video::cue" in css and "background-color:rgba(0,0,0,.25)" in css
          and "text-shadow:0 0 2px #000" in css,
          "::cue is white text on a light translucent box, with a strong outline")
    check(".pl-cues .cue{" in css and "background:rgba(0,0,0,.25)" in css[css.index(".pl-cues .cue{"):css.index(".pl-cues .cue{") + 220]
          and "text-shadow:0 0 2px #000" in css[css.index(".pl-cues{"):css.index(".pl-cues{") + 500],
          "custom overlay matches: translucent box, white text, strong shadow (WebView fallback)")
    check("::-webkit-media-text-track-display-backdrop{background:transparent" in css,
          "native WebKit cue backdrop is forced transparent")
    check("function liftCues(" in js and 'c.line = "auto"' in js, "liftCues is still present")

    print("stats panel")
    chunk = css[css.index(".pl-ss{"):css.index(".pl-ss{") + 900]
    check("grid-template-columns:" in chunk and "1fr" in chunk,
          "stats panel is a 2x2 grid")
    check("left:50%;transform:translateX(-50%)" in css[css.index(".pl-ss{"):css.index(".pl-ss{") + 400],
          "stats panel sits top-center under the title bar")
    check("background:rgba(16,12,22,.38)" in css and "backdrop-filter:blur(14px)" in css[css.index(".pl-ss{"):css.index(".pl-ss{") + 700],
          "stats panel uses a glass / translucent background")
    check(".player.ov-on .pl-ss{opacity:1}" in css, "stats panel fades with the other controls")
    check(".pl-ss .hw-badge{background:var(--acc-fill);color:var(--on-acc)" in css,
          "GPU badge stays the solid purple pill")
    r = js.split("function renderPlayerStat()")[1].split("function renderSysPanel")[0]
    check("api(" not in r and "fetch(" not in r, "player status still makes no requests of its own")
    check("pl-ss-cell" in js and "hw-badge" in r and "Dropped" in r and "CPU" in r and "RAM" in r,
          "renderPlayerStat paints CPU, RAM, GPU/encoder, and Dropped cells")
    check("droppedVideoFrames" in js, "dropped-frame counter is still used")

    print("live VTT conversion (sidecar + embedded)")
    live_subs()


def live_subs():
    ffmpeg = os.environ.get("FFMPEG") or "ffmpeg"
    try:
        subprocess.run([ffmpeg, "-version"], check=True, capture_output=True)
    except Exception as e:
        check(False, "ffmpeg is available for the subtitle sample (%s)" % e)
        return

    media_dir = Path(TMP) / "media"
    media_dir.mkdir(parents=True)
    sidecars = media_dir / "Caption Demo (2026).srt"
    sidecars.write_text(
        "1\n00:00:00,000 --> 00:00:08,000\nHello from the sidecar\n\n"
        "2\n00:00:08,000 --> 00:00:20,000\nStill the sidecar\n",
        encoding="utf-8",
    )
    mp4 = media_dir / "Caption Demo (2026).mp4"
    # short 16:9 clip + an embedded mov_text track, plus the sidecar next to it
    cmd = [
        ffmpeg, "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=0x2a1040:s=1280x720:d=8:r=24",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-f", "srt", "-i", str(sidecars),
        "-map", "0:v", "-map", "1:a", "-map", "2:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-t", "8",
        "-c:a", "aac", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
        "-movflags", "+faststart", str(mp4),
    ]
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    if p.returncode != 0:
        check(False, "ffmpeg built a sample with sidecar + embedded subs: %s" % p.stderr.decode(errors="replace")[-400:])
        return
    check(mp4.is_file() and mp4.stat().st_size > 1000, "sample movie file was written")

    found = media.find_external_subs(mp4)
    check(any(s.get("file", "").endswith(".srt") for s in found),
          "find_external_subs discovers the sidecar .srt: %s" % found)

    raw = media.ffprobe(str(mp4))
    check(bool(raw), "ffprobe reads the sample")
    info = media.summarize_probe(raw)
    subs = json.loads(info.get("subtitle_streams") or "[]")
    text_subs = [s for s in subs if s.get("text")]
    check(len(text_subs) >= 1, "embedded text subtitle stream is probed: %s" % subs)

    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    settings.put("hw_transcode", "off")
    now = int(time.time())
    with db.tx() as c:
        c.execute(
            "INSERT INTO libraries(id,name,kind,path,scan_interval_h,created_at) VALUES(1,'Movies','movies',?,0,?)",
            (str(media_dir), now),
        )
        c.execute(
            "INSERT INTO items(library_id,path,media_type,kind,title,sort_title,year,file_title,"
            "duration,container,vcodec,width,height,size,mtime,added_at,probed,"
            "audio_streams,subtitle_streams,external_subs,meta_status) "
            "VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(mp4), "video", "movie", "Caption Demo", "caption demo", 2026, "Caption Demo",
             8, "mp4", "h264", 1280, 720, mp4.stat().st_size, now, now, 1,
             info.get("audio_streams"), info.get("subtitle_streams"),
             json.dumps(found), "unmatched"),
        )
    item = db.row("SELECT * FROM items")
    pb = server.playback_info(item)
    keys = [s["key"] for s in pb["subtitles"]]
    check(any(k.startswith("e") for k in keys) and any(k.startswith("s") for k in keys),
          "playback lists sidecar and embedded tracks: %s" % pb["subtitles"])

    import uvicorn
    PORT = 8176

    def _run():
        uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning")

    threading.Thread(target=_run, daemon=True).start()

    def call(path, method="GET", data=None, cookie=None, timeout=30):
        headers = {"Accept": "*/*"}
        if cookie:
            headers["Cookie"] = cookie
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(), r.headers.get("Set-Cookie") or ""

    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        check(False, "test server started")
        return

    st, hd, body, setc = call("/api/login", "POST", {"username": "admin", "password": "TestPass14!"})
    check(st == 200, "fake admin login")
    cookie = ""
    # urllib may not expose all set-cookie; parse from setc or from a CookieJar-less fallback
    if "media_server=" in setc or "session=" in setc or "=" in setc:
        cookie = setc.split(";", 1)[0]
    if not cookie:
        # try common names from a raw header walk
        cookie = setc.split(";", 1)[0]
    check(bool(cookie), "login cookie returned (%s)" % (cookie[:40] + "..." if len(cookie) > 40 else cookie))

    iid = item["id"]
    for key in keys:
        try:
            st, hd, body, _ = call("/api/items/%d/subs/%s.vtt" % (iid, key), cookie=cookie, timeout=60)
        except urllib.error.HTTPError as e:
            check(False, "GET /subs/%s.vtt -> %s %s" % (key, e.code, e.read()[:200]))
            continue
        text = body.decode("utf-8", "replace")
        ctype = (hd.get("Content-Type") or hd.get("content-type") or "")
        check(st == 200 and "vtt" in ctype.lower() and text.lstrip("\ufeff").startswith("WEBVTT"),
              "%s.vtt is WebVTT (%s, %d bytes)" % (key, ctype, len(body)))
        if key.startswith("e"):
            check("sidecar" in text.lower() or "Hello from the sidecar" in text,
                  "sidecar VTT contains the cue text")
        else:
            check(len(text) > 20, "embedded VTT is not empty")


if __name__ == "__main__":
    main()
    print("FAILS: %d" % len(fails) if fails else "ALL OK")
    raise SystemExit(1 if fails else 0)
