"""1.5.3: phone library toolbar + filter sheet, 2K/4K quality (GPU only, never upscaled, HEVC in fMP4 HLS),
"use an existing connection" when adding a library. Static + unit checks; no GPU, no network."""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); APP = os.path.join(ROOT, "app")
sys.path.insert(0, ROOT)
os.environ.setdefault("MS_DATA_DIR", tempfile.mkdtemp(prefix="t153-"))
fails = []
def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok: fails.append(msg)
rd = lambda *p: open(os.path.join(*p)).read()
js = rd(APP, "static", "app.js"); css = rd(APP, "static", "style.css"); srv = rd(APP, "server.py")
helper = rd(ROOT, "helpers", "media-server-mount"); cfg = rd(APP, "version.py")
from app import transcode as T, hwaccel as H
check(tuple(int(x) for x in cfg.split('"')[1].split(".")) >= (1, 5, 3), "version >= 1.5.3")
# --- 2K / 4K
check(T.PROFILES["2160p"][:2] == (2160, 25000) and T.PROFILES["1440p"][:2] == (1440, 12000), "H.264 4K 25 / 2K 12 Mbps")
check(T.HEVC_KBPS == {"2160p": 16000, "1440p": 8000}, "HEVC 4K 16 / 2K 8 Mbps")
check(T.valid_profile("2160p") and T.valid_profile("2160p.hevc") and T.valid_profile("1440p.hevc") and not T.valid_profile("1080p.hevc")
      and not T.valid_profile("4320p") and not T.valid_profile("2160p.av1"), "valid_profile: HEVC only for 2K/4K")
check(T.split_profile("2160p.hevc") == ("2160p", "hevc") and T.is_hires("1440p.hevc") and not T.is_hires("1080p"), "split_profile / is_hires")
check(T.fit_box(3840, 1600, 3840, 2160) == (3840, 1600) and T.fit_box(3840, 1600, 2560, 1440) in ((2560, 1066), (2560, 1068)), "fit_box keeps the aspect: %s" % (T.fit_box(3840, 1600, 2560, 1440),))
check(T.fit_box(1920, 1080, 3840, 2160) == (1920, 1080), "fit_box never upscales")
check(T.hires_ok({"width": 3840, "height": 1600}, "2160p") and T.hires_ok({"width": 3590, "height": 2160}, "2160p")
      and not T.hires_ok({"width": 1920, "height": 1080}, "1440p") and T.hires_ok({"width": 2560, "height": 1080}, "1440p"), "hires_ok: by width or height (scope films count)")
pre, vf, enc = H.stage_args("vaapi", "/dev/dri/renderD128", "full", 2160, 16000, width=3840, codec="hevc")
check("hevc_vaapi" in enc and "hvc1" in enc and "w=3840:h=2160" in vf, "VAAPI HEVC 4K: %s %s" % (vf, " ".join(enc)))
pre, vf, enc = H.stage_args("vaapi", "/dev/dri/renderD128", "full", 1440, 12000, width=2560, codec="h264")
check("h264_vaapi" in enc and "w=2560:h=1440" in vf, "VAAPI H.264 2K")
for m, e in (("qsv", "hevc_qsv"), ("nvenc", "hevc_nvenc")):
    _, _, enc = H.stage_args(m, "/dev/dri/renderD128" if m == "qsv" else "0", "full", 2160, 16000, width=3840, codec="hevc")
    check(e in enc, "%s HEVC encoder" % m)
pl = T.playlist({"duration": 18.0}, "", None, fmp4_init="init0.mp4")
check("#EXT-X-VERSION:7" in pl and '#EXT-X-MAP:URI="init0.mp4' in pl and "seg0.m4s" in pl, "fMP4 playlist (VERSION 7, EXT-X-MAP, .m4s)")
check("seg0.ts" in T.playlist({"duration": 18.0}), "H.264 playlist still MPEG-TS")
tc = rd(APP, "transcode.py")
check("frag_discont" in tc and "hls_segment_type" in tc, "fMP4 segments keep their timeline across seeks (frag_discont)")
check("1.2" in tc and "6000" in tc, "2K/4K bitrate capped at 1.2x the source (min 6 Mbps)")
check('"hires_off"' in srv and "need hardware transcoding" in srv and "409" in srv, "API: hires_off note, 409 without a GPU")
check("hevcOK" in js and "hvc1.1.6.L153.B0" in js and "hiresDown" in js and "without tone-mapping" in js, "player: HEVC detection, step-down, HDR note")
check("needs GPU transcoding" in js and "aria-disabled" in js, "CPU servers: 2K/4K shown disabled")
# --- phone library
for k in ("mlHead", "mlSheet", "mlActive", "mlMore", "pushState"):
    check(k in js, "phone library: %s" % k)
check("@media(max-width:820px)" in css.replace(" ", "") and ".mls" in css and "repeat(3,minmax(0,1fr))" in css.replace(" ", ""), "phone CSS: sheet + 3-column grid")
# --- existing connection
check('@app.get("/api/connections")' in srv and "require_admin" in srv.split('@app.get("/api/connections")')[1][:200], "GET /api/connections (admin)")
conn_fn = srv.split("def list_connections")[1].split("\n@app")[0]
check("password" not in conn_fn, "/api/connections never touches a password")
check('stype == "existing"' in srv and "mount_as" in srv and "_within" in srv, "add_library: existing (same share reused, other share via add-as)")
check('src.get("type") == "existing"' in srv, "/api/browse: existing connection")
check(all(a in helper for a in ("add-as)", "browse-as)", "shares-as)", "cred_of")), "helper: add-as / browse-as / shares-as")
check(subprocess.run(["bash", "-n", os.path.join(ROOT, "helpers", "media-server-mount")]).returncode == 0, "helper: bash -n")
check('valid_id "$src"; cmd_browse' in helper and '[ "$id" != "$src" ]' in helper, "helper: src id validated before reading its login")
check("Existing connection" in js and "/api/connections" in js and "conn-list" in js and ".conn-list" in css, "Add library: Existing connection UI")
dl = srv.split("def delete_library")[1].split("\n@app")[0]
check("COUNT(*)" in dl and "share_id" in dl, "delete_library unmounts a share only when no other library uses it")
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
