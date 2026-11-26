"""2.0: offline downloads -- devices (EC P-256 keys, signed requests), signed 30-day grants, device-profile transcodes
(CPU here; the VAAPI/QSV/NVENC command lines are checked), pause-for-playback, quotas, sync (renew / revoke / wipe /
progress), admin views, Activity events, and the schema 10 -> 11 upgrade with its backup.

    python3 tests/test_v20.py

Made-up logins only.  Nothing leaves 127.0.0.1.
"""
import base64
import hashlib
import http.cookiejar
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="ms-v20-")
DATA = TMP + "/data"
os.environ["MS_DATA_DIR"] = DATA
os.environ["MS_OFFLINE_START_DELAY"] = "0"
os.environ["MS_X264_PRESET"] = "ultrafast"

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


# ------------------------------------------------------------------ a 1.9 (schema 10) database first
OLD = ROOT.parent.parent / "v19" / "media-server"
HAD_OLD = OLD.is_dir()
if HAD_OLD:
    env = dict(os.environ, MS_DATA_DIR=DATA, PYTHONPATH=str(OLD))
    out = subprocess.run([sys.executable, "-c", (
        "from app import db, auth; db.migrate(); auth.create_user('boss','fake-boss-pass1',is_admin=True)")],
        cwd=str(OLD), env=env, capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr)

from app import auth, db, hwaccel, keys, offline, preload, server, settings, transcode, useractivity  # noqa: E402
from app.version import __version__  # noqa: E402

PORT = 19000 + os.getpid() % 1000
BASE = "http://127.0.0.1:%d" % PORT


def b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Device:
    """A fake phone: an EC P-256 key (the app keeps it in the Android Keystore) that signs requests."""
    def __init__(self, caps=None, name="Test phone"):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.der = self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.id = None
        self.caps = caps or {"hevc": False, "maxh": 1080}
        self.name = name
        self.skew = 0

    def headers(self, method, path, body=b"", did=None, nonce=None, ts=None):
        ts = str(int(time.time()) + self.skew if ts is None else ts)
        nonce = nonce or secrets.token_urlsafe(18)
        msg = offline.canonical(method, path, ts, nonce, body)
        sig = base64.b64encode(self.key.sign(msg, ec.ECDSA(hashes.SHA256()))).decode()
        return {"X-Movinite-Device": str(did if did is not None else (self.id or "new")), "X-Movinite-Time": ts,
                "X-Movinite-Nonce": nonce, "X-Movinite-Sig": sig}


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method, path, body=None, headers=None, raw=False, dev=None, sign_as=None, cookie=True):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Linux; Android 14) MediaServerAndroid/2.0"}
        if dev is not None:
            h.update(dev.headers(method, path, data or b"", did=sign_as))
        h.update(headers or {})
        r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
        op = self.op if cookie else urllib.request.build_opener()
        try:
            with op.open(r, timeout=60) as resp:
                b = resp.read()
                self.last_headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, (b if raw else (json.loads(b) if b and b[:1] in b"{[" else b.decode(errors="replace")))
        except urllib.error.HTTPError as e:
            b = e.read()
            self.last_headers = {k.lower(): v for k, v in e.headers.items()}
            try:
                return e.code, json.loads(b)
            except Exception:
                return e.code, b.decode(errors="replace")

    def get(self, p, **k):
        return self.req("GET", p, **k)

    def post(self, p, body=None, **k):
        return self.req("POST", p, body if body is not None else {}, **k)

    def put(self, p, body, **k):
        return self.req("PUT", p, body, **k)

    def delete(self, p, **k):
        return self.req("DELETE", p, **k)


def start_server():
    import uvicorn
    db.migrate()
    t = threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"), daemon=True)
    t.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/setup-status", timeout=1)
            return
        except Exception:
            time.sleep(0.1)


def login(name, pw):
    c = Client()
    s, r = c.post("/api/login", {"username": name, "password": pw})
    assert s == 200, (name, s, r)
    return c


def make_video(path, seconds, size="1280x720", vcodec="libx264", extra=()):
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=24" % size,
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds), "-c:v", vcodec,
           "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2"] + list(extra) + [str(path)]
    subprocess.run(cmd, check=True)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(out.stdout or "{}").get("streams", [])


def add_item(c, iid, lib, title, path, w=1280, h=720, vcodec="h264", acodec="aac", dur=4.0, container="matroska"):
    link = path.with_name("%d%s" % (iid, path.suffix))      # items.path is unique: one hard link per item
    if not link.exists():
        os.link(path, link)
    path = link
    st = os.stat(path)
    c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,probed,size,mtime,container,"
              "vcodec,acodec,duration,width,height,pix_fmt,audio_streams,subtitle_streams,external_subs) "
              "VALUES(?,?,?,'video','movie',?,?,?,1,?,?,?,?,?,?,?,?,'yuv420p',?,'[]','[]')",
              (iid, lib, str(path), title, title.lower(), int(time.time()), st.st_size, st.st_mtime, container, vcodec,
               acodec, dur, w, h, json.dumps([{"codec": acodec, "channels": 2, "lang": "eng"}])))


def wait_for(fn, timeout=90, step=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def main():
    print("version / schema 11 upgrade")
    check(tuple(int(x) for x in __version__.split(".")) >= (2, 0), "version is 2.0 or later (%s)" % __version__)
    check(db.SCHEMA_VERSION == 11, "schema 11")
    start_server()
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] == "11", "database migrated to schema 11")
    if HAD_OLD:
        bk = Path(DATA) / "media-server.db.pre-schema11"
        check(bk.is_file(), "schema 10 database snapshot kept as media-server.db.pre-schema11")
        if bk.is_file():
            old = sqlite3.connect(str(bk))
            check(old.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "10", "the snapshot is the schema 10 database")
            old.close()
    else:
        auth.create_user("boss", "fake-boss-pass1", is_admin=True)
    tables = {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    check({"devices", "offline_grants", "offline_jobs"} <= tables, "devices, offline_grants and offline_jobs tables")
    cols = {r[1] for r in db.get().execute("PRAGMA table_info(users)")}
    check({"dl_titles", "dl_gb", "dl_devices"} <= cols, "per-user download limit columns")
    check(keys.ensure() and keys.public_bytes(), "server key available")

    media = Path(TMP) / "media"
    media.mkdir()
    make_video(media / "road.mkv", 4)
    make_video(media / "long.mkv", 40)
    make_video(media / "small.mp4", 3, size="640x360")
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,created_at) VALUES(901,'Family Movies','movies',?,?)", (str(media), now))
        c.execute("INSERT INTO libraries(id,name,kind,path,created_at) VALUES(902,'Private Movies','movies',?,?)", (str(media), now))
        add_item(c, 6001, 901, "Road Film", media / "road.mkv")
        add_item(c, 6002, 902, "Secret Film", media / "road.mkv")
        add_item(c, 6003, 901, "Hevc Film", media / "small.mp4", vcodec="hevc", container="mov,mp4")
        add_item(c, 6004, 901, "Long Film", media / "long.mkv", dur=40.0)
        add_item(c, 6005, 901, "Old Avi", media / "road.mkv", vcodec="mpeg4", acodec="mp3")
        c.execute("UPDATE items SET path=? WHERE id=6005", (str(media / "old.avi"),))
        add_item(c, 6006, 901, "Dts Film", media / "small.mp4", w=640, h=360, acodec="dts", container="mov,mp4")
        add_item(c, 6007, 901, "Other Film", media / "small.mp4", w=640, h=360, container="mov,mp4")
        add_item(c, 6008, 901, "Third Film", media / "small.mp4", w=640, h=360, container="mov,mp4")
    (media / "old.avi").write_bytes(b"\0" * 2048)

    a = login("boss", "fake-boss-pass1")
    for name, role, libs in (("dana", "download", [901]), ("vic", "view", [901]), ("dora", "download", [901])):
        s, r = a.post("/api/users", {"username": name, "password": "fake-pass-%s1" % name, "role": role,
                                     "all_libraries": False, "libraries": libs})
        check(s == 200, "admin adds %s (%s)" % (name, role))
    dana, vic, dora = login("dana", "fake-pass-dana1"), login("vic", "fake-pass-vic1"), login("dora", "fake-pass-dora1")
    check(dana.get("/api/me")[1].get("can_download") is True and vic.get("/api/me")[1].get("can_download") is False,
          "/api/me says who can download")

    print("devices: keys, signatures, roles, limits")
    d1 = Device()
    body = {"pubkey": base64.b64encode(d1.der).decode(), "name": "Dana's S24", "platform": "android", "app_version": "2.0",
            "caps": d1.caps}
    s, r = vic.post("/api/devices", body, dev=d1)
    check(s == 403 and "Viewer + Downloads" in json.dumps(r), "a Viewer can't set up downloads")
    s, r = dana.post("/api/devices", body)
    check(s == 401 and r.get("detail", {}).get("reason") == "missing", "unsigned registration is refused")
    other = Device()
    s, r = dana.req("POST", "/api/devices", body, headers=other.headers("POST", "/api/devices", json.dumps(body).encode()))
    check(s == 401 and r["detail"]["reason"] == "bad_signature", "registration signed by a different key is refused")
    s, r = Client().post("/api/devices", body, dev=d1)
    check(s == 401, "registration needs a signed-in session")
    s, r = dana.post("/api/devices", body, dev=d1)
    check(s == 200 and r.get("device_id") and r.get("server_pubkey"), "Dana registers her phone")
    d1.id = r["device_id"]
    srv_pub = Ed25519PublicKey.from_public_bytes(b64u_dec(r["server_pubkey"]))
    check(r["fp"] == offline.device_fp(d1.der) and r["offline_days"] == 30 and r["wipe_days"] == 30,
          "answer carries the device fingerprint and the 30-day windows")
    check("private" not in json.dumps(r).lower() and "seed" not in json.dumps(r).lower(), "no private key material in the answer")
    s, r2 = dana.post("/api/devices", body, dev=d1)
    check(s == 200 and r2["device_id"] == d1.id, "registering the same key again returns the same device")
    s, r = dora.post("/api/devices", body, dev=d1)
    check(s == 409, "another account can't take over a registered key")

    # replay and clock checks
    path = "/api/offline/options/6001"
    h = d1.headers("GET", path)
    s1, _ = dana.get(path, headers=h)
    s2, r = dana.get(path, headers=h)
    check(s1 == 200 and s2 == 401 and r["detail"]["reason"] == "replay", "a replayed signed request is refused")
    d1.skew = -1000
    s, r = dana.get(path, dev=d1)
    check(s == 401 and r["detail"]["reason"] == "clock" and abs(r["detail"]["server_time"] - time.time()) < 5,
          "a request from a wrong clock is refused with the server time (the app corrects and retries)")
    d1.skew = 0
    s, r = dana.get("/api/offline/options/6001?caps=x", headers=d1.headers("GET", "/api/offline/options/6001"))
    check(s == 401 and r["detail"]["reason"] == "bad_signature", "the query string is covered by the signature")

    print("download options (device profiles)")
    s, o = dana.get("/api/offline/options/6001", dev=d1)
    ids = [p["id"] for p in o.get("profiles", [])]
    check(s == 200 and ids == ["original", "720p", "480p"], "720p source: Original, 720p, 480p (%s)" % ids)
    check(o["default"] == "720p", "default quality is 720p")
    orig = o["profiles"][0]
    check(orig["available"] and orig["bytes"] == os.path.getsize(media / "6001.mkv"), "Original offered (H.264/AAC MKV) with its real size")
    p720 = next(p for p in o["profiles"] if p["id"] == "720p")
    check(0 < p720["bytes"] < 4 * (2160 * 125 * 1.1), "720p size estimate is about 2.2 Mbit/s (%d bytes for 4 s)" % p720["bytes"])
    check(o["usage"]["titles_max"] == 20 and o["usage"]["bytes_max"] == 100 * 1024 ** 3 and o["usage"]["devices_max"] == 3,
          "defaults: 20 titles, 100 GB, 3 devices")
    s, o = dana.get("/api/offline/options/6003", dev=d1)
    check(not o["profiles"][0]["available"] and "HEVC" in o["profiles"][0]["note"], "HEVC original not offered to a phone without HEVC")
    s, o = dana.get("/api/offline/options/6005", dev=d1)
    check(not o["profiles"][0]["available"] and "AVI" in o["profiles"][0]["note"], "AVI original needs converting")
    s, o = dana.get("/api/offline/options/6006", dev=d1)
    check(not o["profiles"][0]["available"] and "DTS" in o["profiles"][0]["note"], "DTS audio original not offered without DTS")
    check([p["id"] for p in o["profiles"]] == ["original", "480p"] and o["default"] == "480p", "360p source: only 480p (default)")
    s, _ = dana.get("/api/offline/options/6002", dev=d1)
    check(s == 404, "options for a library Dana can't see: 404")
    cap = offline.parse_caps({"hevc": True, "dts": True, "maxh": 2160})
    item3 = db.row("SELECT * FROM items WHERE id=6003")
    check(offline.original_ok(item3, cap)[0], "HEVC original offered when the device decodes HEVC")
    check(not offline.original_ok(dict(item3, height=2160), offline.parse_caps({"hevc": True}))[0], "4K original refused on a 1080p device")
    check(not offline.original_ok(dict(item3, color_transfer="smpte2084"), cap)[0], "HDR original refused without HDR support")

    print("VAAPI / GPU command lines")
    real_active = hwaccel.active
    hwaccel.active = lambda: ("vaapi", "/dev/dri/renderD128")
    try:
        it1 = db.row("SELECT * FROM items WHERE id=6001")
        st = offline.stages_for("720p")
        check([x[0] for x in st] == ["full", "enc", "cpu"] and st[0][1][0] == "vaapi", "H.264: full GPU, GPU encode, then CPU")
        check([x[0] for x in offline.stages_for("720p.hevc")] == ["full", "enc"], "HEVC: GPU only")
        cmd = " ".join(offline.build_cmd(it1, "720p", 0, "/tmp/x.mp4", "full", ("vaapi", "/dev/dri/renderD128")))
        check("h264_vaapi" in cmd and "scale_vaapi" in cmd and "vaapi" in cmd.split("-i")[0], "full stage decodes, scales and encodes on VAAPI")
        check("-c:a aac -ac 2" in cmd and "+faststart" in cmd and cmd.endswith("/tmp/x.mp4"), "AAC stereo, fast-start MP4")
        cmdh = " ".join(offline.build_cmd(it1, "720p.hevc", 0, "/tmp/x.mp4", "full", ("vaapi", "/dev/dri/renderD128")))
        check("hevc_vaapi" in cmdh, "HEVC profile uses hevc_vaapi")
        check(offline.use_hevc(offline.parse_caps({"hevc": True})), "HEVC downloads when the phone decodes HEVC and the GPU is on")
        s, o = dana.get("/api/offline/options/6001", dev=d1)
        check(any(p["id"] == "720p" for p in o["profiles"]), "no HEVC for a phone without HEVC even with the GPU")
    finally:
        hwaccel.active = real_active
    check(offline.stages_for("720p.hevc") == [] or hwaccel.active()[0], "no GPU: HEVC downloads are not made on the CPU")
    cmdc = offline.build_cmd(db.row("SELECT * FROM items WHERE id=6001"), "720p", 0, "/tmp/x.mp4", "cpu", (None, None))
    check("libx264" in cmdc and "-progress" in cmdc, "CPU fallback is libx264 with progress output")

    print("grants: Original (ready at once), signed token, ranged download")
    s, g = dana.post("/api/offline/grants", {"item_id": 6001, "profile": "original"})
    check(s == 401, "creating a grant needs the device signature")
    s, g = dana.post("/api/offline/grants", {"item_id": 6002, "profile": "original"}, dev=d1)
    check(s == 404, "no grant for a library Dana can't see")
    s, g = dana.post("/api/offline/grants", {"item_id": 6003, "profile": "original"}, dev=d1)
    check(s == 400, "no Original grant the phone can't play")
    s, g = dana.post("/api/offline/grants", {"item_id": 6001, "profile": "original"}, dev=d1)
    check(s == 201 and g["state"] == "ready" and g.get("token"), "Original grant is ready with a token")
    gid1 = g["id"]
    p_b64, _, sig = g["token"].partition(".")
    try:
        srv_pub.verify(b64u_dec(sig), p_b64.encode())
        tok_ok = True
    except Exception:
        tok_ok = False
    pay = json.loads(b64u_dec(p_b64))
    check(tok_ok, "the token verifies with the server public key the app pinned")
    check(pay["dev"] == offline.device_fp(d1.der) and pay["item"] == 6001 and pay["uid"] == g.get("user_id", pay["uid"])
          and pay["role"] == "download" and pay["gid"] == gid1 and pay["srv"] == keys.server_id(), "token: device, item, role, grant, server")
    check(29.9 * 86400 < pay["exp"] - time.time() <= 30 * 86400, "token expires in 30 days")
    bad = p_b64[:-2] + ("A" if p_b64[-2] != "A" else "B") + p_b64[-1] + "." + sig
    try:
        offline.check_token(bad)
        check(False, "a tampered token is rejected")
    except Exception:
        check(True, "a tampered token is rejected")
    s, again = dana.post("/api/offline/grants", {"item_id": 6001, "profile": "original"}, dev=d1)
    check(s == 200 and again["id"] == gid1, "asking again returns the same grant")
    s, r = dana.post("/api/offline/grants", {"item_id": 6001, "profile": "480p"}, dev=d1)
    check(s == 409 and r["detail"]["error"] == "already_downloaded", "a second quality on the same device needs the first deleted")
    src = (media / "6001.mkv").read_bytes()
    s, body = dana.get("/api/offline/%d/file" % gid1, dev=d1, raw=True)
    hd = dana.last_headers
    check(s == 200 and body == src, "full download matches the file")
    check("no-store" in hd.get("cache-control", "") and "private" in hd.get("cache-control", ""), "Cache-Control: private, no-store")
    s, part = dana.get("/api/offline/%d/file" % gid1, dev=d1, raw=True, headers={"Range": "bytes=100-199"})
    check(s == 206 and part == src[100:200] and dana.last_headers.get("content-range") == "bytes 100-199/%d" % len(src),
          "resumable: a ranged request returns 206 and the right bytes")
    s, _ = dana.get("/api/offline/%d/file" % gid1, raw=True)
    check(s == 401, "the file needs the device signature (a leaked cookie isn't enough)")
    s, _ = Client().get("/api/offline/%d/file" % gid1, dev=d1, raw=True)
    check(s == 401, "the file needs the session too")
    s, _ = dora.get("/api/offline/%d/file" % gid1, dev=d1, raw=True)
    check(s == 403, "another account can't use Dana's device signature")
    s, man = dana.get("/api/offline/%d/manifest" % gid1, dev=d1)
    check(s == 200 and man["title"] == "Road Film" and man["quality"] == "Original" and "subtitles" in man, "manifest: title, quality, subtitles")
    s, done = dana.post("/api/offline/grants/%d/done" % gid1, {"bytes": len(src)}, dev=d1)
    check(s == 200 and done["state"] == "downloaded" and done.get("token"), "device reports the download finished")

    print("device-profile transcode (CPU here), shared cache")
    d2 = Device(name="Dana's tablet")
    b2 = {"pubkey": base64.b64encode(d2.der).decode(), "name": "Dana's tablet", "caps": d2.caps}
    s, r = dana.post("/api/devices", b2, dev=d2)
    d2.id = r.get("device_id")
    check(s == 200 and d2.id and d2.id != d1.id, "a second device")
    s, g = dana.post("/api/offline/grants", {"item_id": 6001, "profile": "720p"}, dev=d2)
    check(s == 201 and g["state"] == "preparing" and not g.get("token"), "720p grant starts as preparing (no token yet)")
    gid2 = g["id"]
    s, _ = dana.get("/api/offline/%d/file" % gid2, dev=d2, raw=True)
    check(s == 409, "file isn't served while preparing")
    ready = wait_for(lambda: (lambda r: r[1] if r[1].get("state") == "ready" else None)(dana.get("/api/offline/grants/%d" % gid2, dev=d2)), 120)
    check(bool(ready) and ready.get("token") and ready.get("sha256"), "transcode finishes: ready, with a token and a checksum")
    if ready:
        s, body = dana.get("/api/offline/%d/file" % gid2, dev=d2, raw=True)
        out = Path(TMP) / "got720.mp4"
        out.write_bytes(body)
        check(hashlib.sha256(body).hexdigest() == ready["sha256"], "downloaded bytes match the checksum in the grant")
        pay = json.loads(b64u_dec(ready["token"].split(".")[0]))
        check(pay["sha"] == ready["sha256"] and pay["prof"] == "720p", "token carries the checksum and quality")
        sts = probe(out)
        v = next((x for x in sts if x["codec_type"] == "video"), {})
        a_ = next((x for x in sts if x["codec_type"] == "audio"), {})
        check(v.get("codec_name") == "h264" and v.get("height") == 720, "720p H.264 video (%sx%s)" % (v.get("width"), v.get("height")))
        check(a_.get("codec_name") == "aac" and a_.get("channels") == 2, "AAC stereo audio")
        s, r = dana.post("/api/offline/grants/%d/done" % gid2, {"sha256": "0" * 64}, dev=d2)
        check(s == 400 and r["detail"]["error"] == "checksum", "a wrong checksum is refused")
        s, r = dana.post("/api/offline/grants/%d/done" % gid2, {"sha256": ready["sha256"]}, dev=d2)
        check(s == 200 and r["state"] == "downloaded", "the right checksum marks it downloaded")
    j = db.row("SELECT * FROM offline_jobs WHERE item_id=6001 AND profile='720p'")
    check(j and j["status"] == "ready" and j["encoder"] == "cpu" and (offline.OFFLINE_DIR / j["path"]).is_file(),
          "the job is cached in data/offline (encoder recorded)")
    d3 = Device(name="Dora's phone")
    s, r = dora.post("/api/devices", {"pubkey": base64.b64encode(d3.der).decode(), "name": "Dora's phone"}, dev=d3)
    d3.id = r.get("device_id")
    s, g3 = dora.post("/api/offline/grants", {"item_id": 6001, "profile": "720p"}, dev=d3)
    check(s == 201 and g3["state"] == "ready" and g3["sha256"] == (ready or {}).get("sha256"),
          "another user asking for the same title and quality gets the cached file at once")

    print("transcodes yield to playback")
    offline.RESUME_IDLE_S = 1
    busy = {"on": True}
    real_busy = offline._busy
    offline._busy = lambda: busy["on"]
    item4 = db.row("SELECT * FROM items WHERE id=6004")
    with db.tx() as c:
        cur = c.execute("INSERT INTO offline_jobs(item_id,profile,audio,status,progress,created_at) VALUES(6004,'480p',0,'manual',0,?)", (now,))
        jid = cur.lastrowid
        c.execute("INSERT INTO offline_grants(user_id,device_id,item_id,profile,audio,job_id,bytes,title,issued_at,expires_at,state) "
                  "VALUES(?,?,6004,'480p',0,?,1,'Long Film',?,?,'preparing')", (r["user"]["id"], d3.id, jid, now, now + 86400))
    jrow = db.row("SELECT * FROM offline_jobs WHERE id=?", (jid,))
    th = threading.Thread(target=offline.run_job, args=(jrow,), daemon=True)
    th.start()
    st = wait_for(lambda: db.row("SELECT status FROM offline_jobs WHERE id=?", (jid,))["status"] == "paused", 20, 0.1)
    proc = offline._cur.get("proc")
    state = ""
    if proc is not None:
        try:
            state = Path("/proc/%d/stat" % proc.pid).read_text().split(")")[1].split()[0]
        except OSError:
            pass
    check(bool(st) and state == "T", "while someone watches, the running ffmpeg is paused (SIGSTOP, state %s)" % state)
    time.sleep(1.5)
    check(db.row("SELECT status FROM offline_jobs WHERE id=?", (jid,))["status"] == "paused", "it stays paused while streaming continues")
    busy["on"] = False
    resumed = wait_for(lambda: db.row("SELECT status FROM offline_jobs WHERE id=?", (jid,))["status"] in ("running", "ready"), 15, 0.1)
    check(bool(resumed), "it carries on once streaming has been idle")
    th.join(120)
    check(db.row("SELECT status FROM offline_jobs WHERE id=?", (jid,))["status"] == "ready", "and finishes")
    # yield_now (called from preload.yield_to_playback when a stream starts)
    with db.tx() as c:
        c.execute("UPDATE offline_jobs SET status='manual', path=NULL WHERE id=?", (jid,))
        c.execute("UPDATE offline_grants SET state='preparing' WHERE job_id=?", (jid,))
    jrow = db.row("SELECT * FROM offline_jobs WHERE id=?", (jid,))
    th = threading.Thread(target=offline.run_job, args=(jrow,), daemon=True)
    th.start()
    wait_for(lambda: offline._cur.get("proc") is not None, 10, 0.05)
    preload.yield_to_playback()
    check(offline._cur.get("paused") is True, "preload.yield_to_playback pauses the offline job at once")
    with db.tx() as c:          # nobody wants it any more: the job stops
        c.execute("UPDATE offline_grants SET state='deleted' WHERE job_id=?", (jid,))
    th.join(30)
    check(not th.is_alive() and db.row("SELECT * FROM offline_jobs WHERE id=?", (jid,)) is None,
          "a job nobody waits for any more is stopped and dropped")
    offline._busy = real_busy

    print("quotas: titles, GB, devices; admins unlimited")
    dana_id = db.row("SELECT id FROM users WHERE username='dana'")["id"]
    s, r = a.put("/api/settings/offline", {"titles": 3})
    check(s == 200 and r["titles"] == 3, "admin sets the title limit to 3")
    s, u0 = dana.get("/api/devices")
    check(u0["usage"]["titles"] == 2 and u0["usage"]["titles_max"] == 3, "Dana uses 2 of 3 titles (%s)" % u0["usage"])
    s, g = dana.post("/api/offline/grants", {"item_id": 6007, "profile": "original"}, dev=d1)
    check(s == 201, "third title fits")
    gid7 = g.get("id")
    s, r = dana.post("/api/offline/grants", {"item_id": 6008, "profile": "original"}, dev=d1)
    check(s == 409 and r["detail"]["error"] == "quota_titles" and "limit of 3" in r["detail"]["detail"], "fourth title is refused with a clear message")
    s, r = a.put("/api/users/%d/download-limits" % dana_id, {"titles": 0, "gb": 0.000001})
    check(s == 200 and r["limits"]["titles"] is None, "per-user override: titles unlimited (0), tiny GB limit")
    s, r = dana.post("/api/offline/grants", {"item_id": 6008, "profile": "original"}, dev=d1)
    check(s == 409 and r["detail"]["error"] == "quota_bytes", "GB limit is enforced")
    s, r = a.put("/api/users/%d/download-limits" % dana_id, {"titles": "", "gb": ""})
    check(s == 200 and r["limits"]["titles"] == 3 and r["limits"]["gb"] == 100, "empty = back to the server default")
    s, _ = dana.delete("/api/offline/grants/%d" % gid7)
    check(s == 200 and dana.get("/api/devices")[1]["usage"]["titles"] == 2, "deleting a download frees the quota")
    s, r = dana.put("/api/settings/offline", {"titles": 99})
    check(s == 403, "only admins change download settings")
    for bad in ({"days": 5}, {"days": 120}, {"titles": -1}, {"cache_gb": 1}):
        check(a.put("/api/settings/offline", bad)[0] == 400, "rejects %s" % bad)
    check(a.put("/api/settings/offline", {"titles": 20})[0] == 200, "title limit back to 20")
    d4 = Device()
    s, r = dana.post("/api/devices", {"pubkey": base64.b64encode(d4.der).decode(), "name": "third"}, dev=d4)
    d4.id = r.get("device_id")
    d5 = Device()
    s, r = dana.post("/api/devices", {"pubkey": base64.b64encode(d5.der).decode(), "name": "fourth"}, dev=d5)
    check(s == 409 and r["detail"]["error"] == "device_limit" and "Devices & downloads" in r["detail"]["detail"],
          "a fourth device is refused (limit 3) and says where to remove one")
    s, _ = dana.delete("/api/devices/%d" % d4.id)
    check(s == 200, "Dana removes a device")
    s, r = dana.post("/api/devices", {"pubkey": base64.b64encode(d5.der).decode(), "name": "fourth"}, dev=d5)
    check(s == 200, "then the new one fits")
    d5.id = r.get("device_id")
    s, r = dana.get("/api/offline/options/6001", dev=d4)
    check(s == 403 and "removed" in json.dumps(r), "a removed device can't be used")
    da = Device()
    s, r = a.post("/api/devices", {"pubkey": base64.b64encode(da.der).decode(), "name": "admin tablet"}, dev=da)
    da.id = r.get("device_id")
    s, o = a.get("/api/offline/options/6001", dev=da)
    check(o["usage"]["titles_max"] is None and o["usage"]["bytes_max"] is None and o["usage"]["devices_max"] is None,
          "admins are unlimited")

    print("sync: renew, revoke, offline deletes, progress, wipe")
    time.sleep(1.1)
    s, sy = dana.post("/api/offline/sync", {"grants": [gid1, 999999], "app_version": "2.0"}, dev=d1, cookie=False)
    check(s == 200 and sy["account"] == "active" and sy["device"] == "active" and not sy["wipe"], "sync works with the device key alone")
    ren = {x["id"]: x for x in sy["renewed"]}
    check(gid1 in ren and json.loads(b64u_dec(ren[gid1]["token"].split(".")[0]))["iat"] > pay["iat"] - 100, "held grant renewed with a new token")
    check(any(x["id"] == 999999 and x["reason"] == "unknown" for x in sy["revoked"]), "unknown grant ids are listed for deletion")
    g1 = db.row("SELECT * FROM offline_grants WHERE id=?", (gid1,))
    check(g1["renewed_at"] and g1["expires_at"] > time.time() + 29 * 86400, "server extended the expiry")
    s, _ = a.delete("/api/offline/grants/%d" % gid1)
    s, sy = dana.post("/api/offline/sync", {"grants": [gid1]}, dev=d1)
    check(any(x["id"] == gid1 and x["reason"] == "removed by an admin" for x in sy["revoked"]), "admin revoke reaches the device on the next sync")
    s, _ = dana.get("/api/offline/%d/file" % gid1, dev=d1, raw=True)
    check(s == 410, "a revoked grant's file is no longer served")
    # progress made offline: newer wins, older is ignored
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(?,6001,10,4,0,?)",
                  (dana_id, int(time.time()) - 50))
    s, sy = dana.post("/api/offline/sync", {"grants": [], "progress": [{"item_id": 6001, "position": 2.5, "duration": 40, "ts": int(time.time()) - 100}]}, dev=d2)
    check(db.row("SELECT position FROM progress WHERE user_id=? AND item_id=6001", (dana_id,))["position"] == 10, "older offline progress doesn't overwrite newer")
    s, sy = dana.post("/api/offline/sync", {"grants": [], "progress": [{"item_id": 6001, "position": 3.0, "duration": 40, "ts": int(time.time())}]}, dev=d2)
    check(sy["progress_saved"] >= 1 and db.row("SELECT position FROM progress WHERE user_id=? AND item_id=6001", (dana_id,))["position"] == 3.0,
          "newer offline progress is saved")
    s, sy = dana.post("/api/offline/sync", {"grants": [gid2], "deleted": [gid2]}, dev=d2)
    check(db.row("SELECT state FROM offline_grants WHERE id=?", (gid2,))["state"] == "deleted" and any(x["id"] == gid2 for x in sy["revoked"]),
          "downloads deleted while offline are reported on sync and free the quota")
    # library access removed
    s, g = dana.post("/api/offline/grants", {"item_id": 6007, "profile": "original"}, dev=d2)
    gid7 = g["id"]
    a.put("/api/users/%d" % dana_id, {"all_libraries": False, "libraries": [902]})
    s, sy = dana.post("/api/offline/sync", {"grants": [gid7]}, dev=d2)
    check(any(x["id"] == gid7 and x["reason"] == "no longer shared with you" for x in sy["revoked"]), "library access removed: revoked on sync")
    a.put("/api/users/%d" % dana_id, {"all_libraries": False, "libraries": [901]})
    # role change to Viewer -> wipe
    s, g = dana.post("/api/offline/grants", {"item_id": 6008, "profile": "original"}, dev=d2)
    gid8 = g["id"]
    a.put("/api/users/%d" % dana_id, {"role": "view"})
    s, sy = dana.post("/api/offline/sync", {"grants": [gid8]}, dev=d2)
    check(sy["account"] == "no_downloads" and sy["wipe"] and any(x["id"] == gid8 for x in sy["revoked"]),
          "role changed to Viewer: the app is told to wipe its downloads")
    a.put("/api/users/%d" % dana_id, {"role": "download"})
    # disabled account -> device revoked, wipe
    a.put("/api/users/%d" % dana_id, {"disabled": True})
    s, sy = dana.post("/api/offline/sync", {"grants": []}, dev=d1, cookie=False)
    check(sy["account"] == "disabled" and sy["device"] == "revoked" and sy["wipe"], "disabled account: device revoked, wipe")
    a.put("/api/users/%d" % dana_id, {"disabled": False})
    # deleted account -> tombstone still answers
    dora_id = db.row("SELECT id FROM users WHERE username='dora'")["id"]
    s, _ = a.delete("/api/users/%d" % dora_id)
    s, sy = Client().post("/api/offline/sync", {"grants": [g3["id"]]}, dev=d3, cookie=False)
    check(s == 200 and sy["account"] == "deleted" and sy["wipe"] and sy["revoked"], "deleted account: its phone still gets a signed wipe answer")
    s, sy = Client().post("/api/offline/sync", {"grants": []}, dev=Device(), cookie=False, sign_as=d1.id)
    check(s == 401, "sync signed by the wrong key is refused")
    # the app's Sign out: device-signed, no cookie needed; frees the device slot and the next sync says wipe
    d5 = Device(name="Dana's tablet")
    dana = login("dana", "fake-pass-dana1")   # disabling her account above ended her sessions
    s, r5 = dana.post("/api/devices", {"pubkey": base64.b64encode(d5.der).decode(), "name": d5.name}, dev=d5)
    d5.id = r5.get("device_id") if isinstance(r5, dict) else None
    s, fr = Client().post("/api/devices/forget", {}, dev=d5, cookie=False)
    row5 = db.row("SELECT revoked_at, revoke_reason FROM devices WHERE id=?", (d5.id,)) if d5.id else None
    check(s == 200 and bool(row5) and bool(row5["revoked_at"]) and row5["revoke_reason"] == "signed out on the device", "app sign-out revokes its own device (device-signed, no cookie)")
    s, sy = Client().post("/api/offline/sync", {"grants": []}, dev=d5, cookie=False)
    check(s == 200 and sy["wipe"], "after sign-out the old key only gets a wipe answer")
    check(Client().post("/api/devices/forget", {}, cookie=False)[0] == 401, "forget needs a device signature")

    print("admin view, Activity")
    s, ad = a.get("/api/admin/offline")
    names = [x["username"] for x in ad.get("users", [])]
    check(s == 200 and "dana" in names and "vic" not in names, "Settings > Downloads lists users with downloads (not plain Viewers)")
    check(isinstance(ad.get("jobs"), list) and "cache" in ad and ad["encoder"] in ("CPU", "GPU (VAAPI)", "GPU (Quick Sync)", "GPU (NVENC)"),
          "with the job queue, cache size and encoder")
    check(vic.get("/api/admin/offline")[0] == 403, "admin only")
    useractivity.flush()
    kinds = {r_["kind"] for r_ in db.rows("SELECT kind FROM activity")}
    want = {"device_registered", "device_revoked", "download_requested", "download_ready", "download_started",
            "download_complete", "download_deleted", "download_revoked"}
    check(want <= kinds, "download events are in Activity (missing: %s)" % sorted(want - kinds))
    s, ev = a.get("/api/admin/activity?group=downloads&limit=500")
    check(s == 200 and ev["events"] and all(e["kind"] in useractivity.KINDS["downloads"] for e in ev["events"]),
          "Activity filter: Downloads")
    details = " ".join((r_["detail"] or "") for r_ in db.rows("SELECT detail FROM activity"))
    check("." not in "".join(x for x in details.split() if len(x) > 80) or ready is None or ready["token"] not in details,
          "grant tokens are never written to Activity")

    print("offline cache LRU")
    settings.put("offline_cache_gb", "5")
    junk = []
    for k in range(3):
        f = offline.OFFLINE_DIR / ("junk%d.mp4" % k)
        f.write_bytes(b"x")
        junk.append(f)
        with db.tx() as c:
            c.execute("INSERT INTO offline_jobs(item_id,profile,audio,status,path,bytes,created_at,finished_at,last_access) "
                      "VALUES(?,?,0,'ready',?,?,?,?,?)", (7000 + k, "480p", f.name, 3 * 1024 ** 3, now, now, now + k))
    offline.evict_lru()
    left = [f.exists() for f in junk]
    check(left == [False, False, True], "oldest cached files are removed above the cap (%s)" % left)

    print("files")
    upd = (ROOT / "update.sh").read_text()
    check("pre-schema11" in upd or "schema 11" in upd, "update.sh backs up the database before schema 11")
    check((ROOT / "CHANGELOG.md").read_text().find("## 2.0") != -1, "CHANGELOG has 2.0")
    js = (ROOT / "app/static/app.js").read_text()
    check("function viewDownloads(" in js and "offlineCaps" in js and "function downloadDialog(" in js, "web UI: Downloads tab and download dialog")
    check("Devices & downloads" in js and "/api/admin/offline" in js, "web UI: Devices & downloads and the admin Downloads tab")
    check("studio" in js.lower(), "web UI help says protection isn't studio-grade")
    r = subprocess.run(["node", "--check", str(ROOT / "app/static/app.js")], capture_output=True, text=True)
    check(r.returncode == 0, "app.js parses (%s)" % r.stderr.strip()[:200])

    print()
    if fails:
        print("FAILED %d:" % len(fails))
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("all 2.0 checks passed")


if __name__ == "__main__":
    main()
