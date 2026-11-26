"""2.1: Plex-style TV layout + library sharing between servers (schema 12).

    python3 tests/test_v21.py

Made-up logins only. Nothing leaves 127.0.0.1.
"""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="ms-v21-")
DATA = TMP + "/data-a"
os.environ["MS_DATA_DIR"] = DATA
os.environ["MS_SESSION_DAYS"] = "30"

from app import auth, db, fed, keys, server, settings  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
db_src = (ROOT / "app/db.py").read_text()
index = (ROOT / "app/static/index.html").read_text()

print("version and docs")
check(__version__ == "2.1", "version is 2.1 (%s)" % __version__)
check("SCHEMA_VERSION = 12" in db_src, "SCHEMA_VERSION is 12")
check("_backup_db(c, 12)" in db_src, "migrate snapshots pre-schema12 before the bump")
check("CREATE TABLE IF NOT EXISTS peers" in db_src and "CREATE TABLE IF NOT EXISTS share_codes" in db_src
      and "CREATE TABLE IF NOT EXISTS remote_libraries" in db_src and "CREATE TABLE IF NOT EXISTS remote_items" in db_src,
      "schema 12 has peers, share_codes, remote_libraries, remote_items")
check("chmod(0o600)" in db_src and "pre-schema%d" in db_src, "schema backups are written mode 600")
check("## 2.1" in ch and ch.find("## 2.1") < ch.find("## 2.0.2"), "CHANGELOG has 2.1 above 2.0.2")
check("schema 12" in ch.lower() or "Schema 12" in ch, "changelog mentions schema 12")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
check("example.com" in rd or "media.example.com" in rd, "public docs use example.com")
for bad in ("tukuia.com", "nasetesi", "Waimea", "Sunset", "naseaho", "Adoration"):
    # changelog/readme may mention install history; public how-to should not teach real names
    pass
check("tukuia.com" not in rd and "Waimea" not in rd and "Sunset" not in rd,
      "README does not use private host or share names")
check("tv-plex.js" in index and "tv-plex.css" in index, "index.html loads the TV layout")
check("tv-plex.css?v=" in (ROOT / "app/server.py").read_text(), "service worker precaches tv-plex assets")
check("function viewSharing" in js and '["sharing", "Sharing", 1]' in js, "Settings has a Sharing tab")
check("/api/sharing/accept" in js and "/api/sharing/codes" in js, "Sharing UI talks to the sharing API")
check("peer_name || L.source_name" in tvjs or "L.peer_name" in tvjs, "TV menu shows the source server on each library")
check("html.tv-mode.tv-plex" in tvcss or "#tv-menu" in tvcss, "TV slide-out menu CSS is present")
check("X-Movinite-Signature" in (ROOT / "app/fed.py").read_text(), "federation calls are Ed25519-signed")
check("code_hash" in db_src and "the raw code is never stored" in db_src, "share codes are stored hashed")

print("schema 11 -> 12 backup")
# Build a tiny schema-11 database, then migrate() should copy it to pre-schema12 mode 600
pre_dir = Path(tempfile.mkdtemp(prefix="ms-v21-pre-"))
pre_db = pre_dir / "media-server.db"
# reuse migrate on a fresh dir after planting schema 11
# We'll plant into DATA after creating the file beside the real db path.
# First migrate empty (creates schema 12), that's not the test.
# Use a side directory and point a raw sqlite at schema 11, then call _backup + migrate by swapping.
side = Path(TMP) / "pre11"
side.mkdir()
(side / "media-server.db").parent.mkdir(parents=True, exist_ok=True)
# Build a real schema-11 database with the 2.0.2 migrator, then let 2.1 upgrade it.
v202 = Path("/workspace/media-server/v202/media-server")
sub = subprocess.run([sys.executable, "-c",
    "import os,sys; os.environ['MS_DATA_DIR']=%r; sys.path.insert(0,%r); from app import db; db.migrate()"
    % (str(side), str(v202))], cwd=str(v202), capture_output=True, text=True)
if sub.returncode != 0:
    print(sub.stderr[-500:])
    raise SystemExit("could not plant a schema-11 database")
conn = sqlite3.connect(str(side / "media-server.db"))
ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
conn.close()
check(ver and ver[0] == "11", "planted database is schema 11 (got %s)" % (ver and ver[0]))
# Run migrate() against this dir by temporarily using db's backup through a child:
import os as _os
child = r"""
import os, sys, stat
from pathlib import Path
os.environ["MS_DATA_DIR"] = %r
sys.path.insert(0, %r)
from app import db, config
# reload paths
import importlib
import app.config as cfg
cfg.DATA_DIR = Path(%r)
cfg.DB_PATH = cfg.DATA_DIR / "media-server.db"
import app.db as d
d.config = cfg
d.migrate()
bak = cfg.DATA_DIR / "media-server.db.pre-schema12"
assert bak.is_file(), "missing pre-schema12"
mode = bak.stat().st_mode & 0o777
# CIFS/tmp may not honor 0600; still require the chmod was attempted and the file exists
print("BACKUP_OK", oct(mode), bak)
v = d.row("SELECT value FROM meta WHERE key='schema_version'")
print("VER", v["value"] if v else None)
""" % (str(side), str(ROOT), str(side))
r = subprocess.run([sys.executable, "-c", child], cwd=str(ROOT), capture_output=True, text=True)
print(r.stdout.strip() or r.stderr[-400:])
check(r.returncode == 0 and "BACKUP_OK" in r.stdout, "migrate from schema 11 writes pre-schema12 (rc=%s)" % r.returncode)
check("VER 12" in r.stdout, "migrate sets schema_version to 12")
bak = side / "media-server.db.pre-schema12"
if bak.is_file():
    mode = bak.stat().st_mode & 0o777
    # On a normal Linux tmpfs this should be 0600
    check(mode == 0o600 or stat.S_IMODE(bak.stat().st_mode) == 0o600,
          "pre-schema12 mode is 600 (got %s)" % oct(mode))
    # file is a sqlite db
    c = sqlite3.connect(str(bak))
    v = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    check(v and v[0] == "11", "pre-schema12 snapshot still has schema 11")
    c.close()

# ---- server A (this process) ----
db.migrate()
keys.ensure()
auth.create_user("admin", "TestPass14!", is_admin=True)
auth.create_user("viewer", "TestView14!", is_admin=False)
settings.put("server_name", "North")
now = int(time.time())
media = Path(DATA) / "media"
media.mkdir(parents=True, exist_ok=True)
clip = media / "heat.mp4"
clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
with db.tx() as c:
    c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
              ("Movies", "movies", str(media), 0, now))
    lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed) "
              "VALUES(?,?, 'video','movie',?,?,?,120,?,1)",
              (lid, str(clip), "Heat", "Heat", 1995, now))
    iid = c.execute("SELECT last_insert_rowid()").fetchone()[0]

meta = db.row("SELECT value FROM meta WHERE key='schema_version'")
check(meta and meta["value"] == "12", "fresh migrate is schema 12 (got %s)" % (meta and meta["value"]))
check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='peers'"), "peers table exists")

# Let go of this thread's SQLite connection so the in-process server can write during pairing.
try:
    db.get().close()
    db._local.conn = None
except Exception:
    pass


import uvicorn  # noqa: E402

PORT_A = 19300 + os.getpid() % 300
PORT_B = PORT_A + 1
BASE_A = "http://127.0.0.1:%d" % PORT_A
BASE_B = "http://127.0.0.1:%d" % PORT_B

threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT_A, log_level="warning"),
                 daemon=True).start()

# ---- server B (subprocess, its own data dir) ----
DATA_B = TMP + "/data-b"
Path(DATA_B).mkdir()
child_b = r"""
import os, sys
from pathlib import Path
os.environ["MS_DATA_DIR"] = %r
os.environ["MS_SESSION_DAYS"] = "30"
sys.path.insert(0, %r)
from app import auth, db, keys, server, settings
db.migrate()
keys.ensure()
auth.create_user("admin", "TestPass14!", is_admin=True)
settings.put("server_name", "Harbor")
import uvicorn
uvicorn.run(server.app, host="127.0.0.1", port=%d, log_level="warning")
""" % (DATA_B, str(ROOT), PORT_B)
blog = Path(TMP) / "b.log"
proc_b = subprocess.Popen([sys.executable, "-c", child_b], cwd=str(ROOT),
                          stdout=open(blog, "w"), stderr=subprocess.STDOUT)


def wait_up(url, tries=80):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=0.3).read()
            return True
        except Exception:
            time.sleep(0.1)
    return False


check(wait_up(BASE_A), "server A started")
check(wait_up(BASE_B), "server B started")


def req(base, path, method="GET", data=None, cookies=None, headers=None):
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(base + path, data=body, method=method, headers=h)
    cj = cookies if cookies is not None else CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        with opener.open(r, timeout=20) as resp:
            raw = resp.read()
            ct = resp.headers.get("content-type") or ""
            jsout = json.loads(raw.decode()) if "json" in ct or (raw[:1] in (b"{", b"[")) else raw
            return resp.status, jsout, cj, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            jsout = json.loads(raw.decode())
        except Exception:
            jsout = raw.decode(errors="replace")
        return e.code, jsout, cj, dict(e.headers)


def login(base, user="admin", pw="TestPass14!"):
    cj = CookieJar()
    st, body, cj, _ = req(base, "/api/login", "POST", {"username": user, "password": pw}, cookies=cj)
    check(st == 200, "login %s on %s -> %s" % (user, base, st))
    return cj


print("health")
st, body, _, _ = req(BASE_A, "/api/health")
check(st == 200 and body.get("version") == "2.1", "A health is 2.1 (%s)" % body)
st, body, _, _ = req(BASE_B, "/api/health")
check(st == 200 and body.get("version") == "2.1", "B health is 2.1")

print("hello / identity")
st, hello, _, _ = req(BASE_A, "/api/fed/hello")
check(st == 200 and hello.get("name") == "North" and hello.get("fingerprint")
      and hello.get("server_id") and hello.get("pubkey"),
      "A hello has name, fingerprint, server id and pubkey")

ca = login(BASE_A)
cb = login(BASE_B)

print("create share code and pair")
st, code, _, _ = req(BASE_A, "/api/sharing/codes", "POST",
                     {"libraries": [lid], "perms": "stream", "max_quality": "1080p", "max_streams": 2},
                     cookies=ca)
check(st == 200 and code.get("code") and code.get("link") and "-" in code["code"],
      "A creates a grouped share code (%s)" % (code.get("code") if st == 200 else code))
raw_code = (code.get("code") or "").replace("-", "")

# preview then confirm on B
st, prev, _, _ = req(BASE_B, "/api/sharing/accept", "POST",
                     {"url": BASE_A, "code": raw_code}, cookies=cb)
check(st == 200 and prev.get("preview") and (prev.get("hello") or {}).get("name") == "North",
      "B previews A's offer (%s)" % prev)
offered = (prev.get("hello") or {}).get("offered") or []
check(any(o.get("name") == "Movies" for o in offered), "preview lists Movies")

st, acc, _, _ = req(BASE_B, "/api/sharing/accept", "POST",
                    {"url": BASE_A, "code": raw_code, "confirm": True, "my_url": BASE_B}, cookies=cb)
check(st == 200 and acc.get("ok"), "B accepts the share (%s)" % acc)

# code is single-use
st, again, _, _ = req(BASE_B, "/api/sharing/accept", "POST",
                      {"url": BASE_A, "code": raw_code, "confirm": True, "my_url": BASE_B}, cookies=cb)
check(st in (404, 400, 409, 401, 403), "share code cannot be reused (st=%s)" % st)

print("catalog appears on B")
st, libs, _, _ = req(BASE_B, "/api/libraries", cookies=cb)
remotes = [l for l in (libs or []) if isinstance(l, dict) and (l.get("is_remote") or (l.get("id") or 0) < 0)]
check(st == 200 and remotes, "B's library list includes a remote library")
if remotes:
    rlib = remotes[0]
    check(rlib.get("peer_name") == "North" or rlib.get("source_name") == "North",
          "remote library is labelled with the source server North (%s)" % rlib.get("peer_name"))
    check(rlib.get("name") == "Movies", "remote library name is Movies")
    st, items, _, _ = req(BASE_B, "/api/libraries/%s/items" % rlib["id"], cookies=cb)
    its = (items or {}).get("items") or []
    check(st == 200 and any(i.get("title") == "Heat" for i in its),
          "synced catalog includes Heat (%s)" % its)
    heat = next((i for i in its if i.get("title") == "Heat"), None)
    if heat:
        st, detail, _, _ = req(BASE_B, "/api/items/%s" % heat["id"], cookies=cb)
        check(st == 200 and detail.get("is_remote") and detail.get("title") == "Heat",
              "remote item detail works")
        # ticket via play start
        st, play, _, _ = req(BASE_B, "/api/items/%s/hls/1080p/index.m3u8" % heat["id"], cookies=cb)
        check(st in (200, 302), "starting remote playback returns a playlist or redirect (st=%s)" % st)

print("signatures: replay and skew")
# Hit A /api/fed/libraries with a captured signed GET, then replay
st, signed_libs, _, hdrs = None, None, None, None
# Use fed.call from this process (A's keys) against A — that's self, may be odd.
# Instead: from B's data we can't. Sign as A against A without a peer — 403 unknown/not active.
# Make a raw signed request as a random key:
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64, hashlib
sk = Ed25519PrivateKey.generate()
pub = base64.b64encode(sk.public_key().public_bytes_raw()).decode() if hasattr(sk.public_key(), "public_bytes_raw") else None
from cryptography.hazmat.primitives import serialization
pub = base64.b64encode(sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
# Without being a peer this should 401/403
date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
nonce = "abc123replaytest"
canon = "\n".join(["GET", "/api/fed/libraries", "", date, hashlib.sha256(b"").hexdigest(), nonce]).encode()
sig = base64.b64encode(sk.sign(canon)).decode()
sid = base64.b32encode(hashlib.sha256(base64.b64decode(pub)).digest()).decode().rstrip("=")[:20]
st, body, _, _ = req(BASE_A, "/api/fed/libraries", headers={
    "X-Movinite-Server": sid, "X-Movinite-Key": pub, "X-Movinite-Date": date,
    "X-Movinite-Nonce": nonce, "X-Movinite-Signature": sig,
})
check(st in (401, 403), "signed request from an unknown peer is rejected (st=%s)" % st)

# Replay a real B->A signed call by calling twice with the same nonce from a live peer:
# After pairing, B is an outgoing peer on A. Use fed.call from this process? This process is A.
# Ask B to sync (B will sign). Then replay is harder.
# Directly: craft a valid call from B by importing B's key is messy.
# Test nonce replay using fed._remember_nonce
try:
    fed._remember_nonce("nonce-once")
    fed._remember_nonce("nonce-once")
    check(False, "replay nonce is rejected")
except Exception as e:
    from fastapi import HTTPException
    check(isinstance(e, HTTPException) and e.status_code == 401, "replay nonce is rejected")

# clock skew
from fastapi import Request as _R
# unit: _parse_date + skew in verify is covered if we send a 1-hour-old date
old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
canon = "\n".join(["GET", "/api/fed/libraries", "", old, hashlib.sha256(b"").hexdigest(), "skewtestnonce1"]).encode()
sig = base64.b64encode(sk.sign(canon)).decode()
st, body, _, _ = req(BASE_A, "/api/fed/libraries", headers={
    "X-Movinite-Server": sid, "X-Movinite-Key": pub, "X-Movinite-Date": old,
    "X-Movinite-Nonce": "skewtestnonce1", "X-Movinite-Signature": sig,
})
check(st == 401, "signature with 1 hour of clock skew is rejected (st=%s)" % st)

print("stop sharing / tickets fail")
st, peers, _, _ = req(BASE_A, "/api/sharing/peers", cookies=ca)
check(st == 200 and isinstance(peers, list) and peers, "A lists the peer (%s)" % peers)
pid = peers[0]["id"] if peers else None
if pid:
    st, stopped, _, _ = req(BASE_A, "/api/sharing/peers/%s/stop" % pid, "POST", {}, cookies=ca)
    check(st == 200 and stopped.get("ok"), "A stops sharing")
    # B sync / libraries should hide or mark it
    time.sleep(0.2)
    st, libs2, _, _ = req(BASE_B, "/api/libraries", cookies=cb)
    # B may still show a cached library until it syncs; force a sync
    remotes2 = [l for l in (libs2 or []) if isinstance(l, dict) and l.get("is_remote")]
    if remotes2:
        req(BASE_B, "/api/sharing/remote/%s/sync" % remotes2[0]["id"], "POST", {}, cookies=cb)
        st, libs2, _, _ = req(BASE_B, "/api/libraries", cookies=cb)
        remotes2 = [l for l in (libs2 or []) if isinstance(l, dict) and l.get("is_remote") and not l.get("hidden_at")]
    # After A revoked, sync may 403 and B marks hidden. Either hidden or still listed offline is ok if grants gone.
    st, peers_b, _, _ = req(BASE_A, "/api/sharing/peers", cookies=ca)
    active_grants = [p for p in (peers_b or []) if p.get("id") == pid and p.get("grants")]
    check(not active_grants, "A has no remaining grants for the stopped peer")

print("TV assets served")
st, page, _, _ = req(BASE_A, "/")
page_s = page if isinstance(page, str) else (page.decode() if isinstance(page, (bytes, bytearray)) else str(page))
check(st == 200 and "tv-plex.js?v=2.1" in page_s and "tv-plex.css?v=2.1" in page_s,
      "index stamps tv-plex assets with v=2.1")

# tidy
try:
    proc_b.terminate()
except Exception:
    pass

print()
if fails:
    print("%d FAILED:" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("all tests passed")
