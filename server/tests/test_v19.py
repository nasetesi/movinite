"""1.9: roles + per-library access, email invites (Connect Gmail, mocked), hashed sessions + devices,
trusted proxies (lockout fix), the server key, and Settings > Activity.

    python3 tests/test_v19.py

Uses only a fake Google (tests/mock_google.py) and made-up logins. Nothing leaves 127.0.0.1.
"""
import base64
import csv
import email
import email.policy
import http.cookiejar
import io
import json
import os
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="ms-v19-")
DATA = TMP + "/data"
os.environ["MS_DATA_DIR"] = DATA
os.environ["MS_GMAIL_BACKOFF_SCALE"] = "0.001"

sys.path.insert(0, str(HERE))
import mock_google  # noqa: E402

GPORT = mock_google.start()
G = "http://127.0.0.1:%d" % GPORT
os.environ["MS_GOOGLE_AUTH_URL"] = G + "/o/oauth2/v2/auth"
os.environ["MS_GOOGLE_TOKEN_URL"] = G + "/token"
os.environ["MS_GOOGLE_REVOKE_URL"] = G + "/revoke"
os.environ["MS_GMAIL_API_BASE"] = G

import mock_smtp  # noqa: E402
SMTP_TLS = mock_smtp.start("starttls")     # pretends to be smtp.gmail.com:587
SMTP_SSL = mock_smtp.start("ssl")          # a generic provider on "465"
SMTP_PLAIN = mock_smtp.start("plain")      # a LAN relay without sign-in
os.environ["MS_GMAIL_SMTP_HOST"] = "localhost"
os.environ["MS_GMAIL_SMTP_PORT"] = str(SMTP_TLS.port)
os.environ["MS_SMTP_CAFILE"] = mock_smtp.CAFILE
os.environ["MS_MAIL_BACKOFF_SCALE"] = "0.001"

import logging  # noqa: E402
LOGBUF = io.StringIO()
_lh = logging.StreamHandler(LOGBUF)
_lh.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_lh)
logging.getLogger().setLevel(logging.DEBUG)

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


# ------------------------------------------------------------------ a 1.8.1 (schema 9) database first
OLD = ROOT.parent.parent / "v181" / "media-server"
OLD_TOKEN = None
if OLD.is_dir():
    env = dict(os.environ, MS_DATA_DIR=DATA, PYTHONPATH=str(OLD))
    out = subprocess.run([sys.executable, "-c", (
        "from app import db, auth; db.migrate(); uid=auth.create_user('oldadmin','old-fake-pass-1',is_admin=True);"
        "auth.create_user('oldviewer','old-fake-pass-2'); print(auth.new_session(uid))")],
        cwd=str(OLD), env=env, capture_output=True, text=True)
    OLD_TOKEN = (out.stdout.strip().splitlines() or [""])[-1]

from app import auth, db, gmail, invites, keys, mailer, netutil, server, settings, useractivity  # noqa: E402
from app.version import __version__  # noqa: E402

PORT = 18000 + os.getpid() % 1000
BASE = "http://127.0.0.1:%d" % PORT


class Client:
    def __init__(self, headers=None):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.headers = headers or {}

    def req(self, method, path, body=None, headers=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/120 Mobile"}
        h.update(self.headers)
        h.update(headers or {})
        r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
        try:
            with self.op.open(r, timeout=20) as resp:
                b = resp.read()
                return resp.status, (b if raw else (json.loads(b) if b and b[:1] in b"{[" else b.decode()))
        except urllib.error.HTTPError as e:
            b = e.read()
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

    def cookie(self):
        for c in self.jar:
            if c.name == auth.COOKIE:
                return c.value


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


def db_bytes():
    out = b""
    for p in Path(DATA).rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


def main():
    print("version / docs / UI")
    check(__version__ == "1.9" or __version__.startswith("1.9."), "version is 1.9")
    ch = (ROOT / "CHANGELOG.md").read_text()
    check(ch.find("## 1.9") != -1 and ch.find("## 1.9") < ch.find("## 1.8.1"), "CHANGELOG has 1.9 above 1.8.1")
    check((ROOT / "docs/gmail-setup.md").is_file() and (ROOT / "app/static/gmail-setup.html").is_file(),
          "docs/gmail-setup.md and the in-app guide exist")
    guide = (ROOT / "docs/gmail-setup.md").read_text()
    check("http://localhost/movinite-gmail-callback" in guide and "/api/gmail/callback" in guide
          and "gmail.send" in guide and "In production" in guide, "guide lists both redirect URIs, the scope, and publishing")
    check(guide.index("apppasswords") < guide.index("Advanced: Connect Gmail") and "2-Step Verification" in guide,
          "guide leads with the app password (2-Step Verification) and keeps Connect Gmail as advanced")
    req = (ROOT / "requirements.txt").read_text()
    check("cryptography" in req, "requirements.txt has cryptography")
    js = (ROOT / "app/static/app.js").read_text()
    html = (ROOT / "app/static/index.html").read_text()
    check('"Scans"' in js and '"Activity"' in js and '"Email"' in js and "Scan activity" not in js.split("const tabs")[1][:800],
          "Settings tabs: Scans (renamed), Activity, Email")
    check("/static/qr.js" in html and (ROOT / "app/static/qr.js").is_file(), "QR encoder is shipped")
    check("gm.status" not in js and "/api/gmail/status" not in js and '"/api/mail/status"' in js,
          "Users and the invite dialog use the method-neutral /api/mail/status")
    check("function showJoin(" in js and "await showJoin(inv[1])" in js, "join page for invite links")
    r = subprocess.run(["node", "--check", str(ROOT / "app/static/app.js")], capture_output=True, text=True)
    check(r.returncode == 0, "app.js parses (node --check) " + r.stderr[:200])

    print("migration to schema 10")
    db.migrate()
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] in ("10", 10) if db.row("SELECT name FROM sqlite_master WHERE name='meta'") else True,
          "schema_version is 10")
    if OLD_TOKEN:
        bk = Path(DATA) / "media-server.db.pre-schema10"
        check(bk.is_file() and stat.S_IMODE(bk.stat().st_mode) == 0o600, "pre-schema10 backup written, mode 600")
        con = sqlite3.connect(str(bk))
        check(con.execute("SELECT COUNT(*) FROM sessions WHERE token=?", (OLD_TOKEN,)).fetchone()[0] == 1, "backup is the old database")
        con.close()
        check(not db.row("SELECT 1 FROM sessions WHERE token=?", (OLD_TOKEN,)), "raw session token no longer stored")
        check(db.row("SELECT 1 FROM sessions WHERE token=?", (auth.token_hash(OLD_TOKEN),)) is not None, "session token hashed in place")
        check(db.row("SELECT role FROM users WHERE username='oldadmin'")["role"] == "admin"
              and db.row("SELECT role FROM users WHERE username='oldviewer'")["role"] == "view", "roles backfilled from is_admin")
        check(db.row("SELECT all_libraries FROM users WHERE username='oldviewer'")["all_libraries"] == 1,
              "existing users keep every library")
    else:
        print("  (skip: v181 tree not found)")

    print("server key")
    keys.ensure()
    kf = keys.KEY_FILE
    check(kf.is_file() and stat.S_IMODE(kf.stat().st_mode) == 0o600 and len(kf.read_bytes()) == 32, "Ed25519 seed is 32 bytes, mode 600")
    check(stat.S_IMODE(keys.SECRETS_DIR.stat().st_mode) == 0o700, "secrets dir is 700")
    fp = keys.fingerprint()
    check(re.match(r"^MOVI-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$", fp or "") is not None, "fingerprint looks like MOVI-XXXX-XXXX-XXXX (%s)" % fp)
    blob = keys.seal("t/x", {"v": "hello"})
    check(blob.startswith(b"MVS1") and keys.unseal("t/x", blob) == {"v": "hello"}, "seal/unseal round trip")
    try:
        keys.unseal("t/other", blob)
        check(False, "a different purpose can't unseal")
    except Exception:
        check(True, "a different purpose can't unseal")

    start_server()
    a = Client()
    if OLD_TOKEN:
        a.jar.set_cookie(http.cookiejar.Cookie(0, auth.COOKIE, OLD_TOKEN, None, False, "127.0.0.1", False, False, "/", True,
                                               False, None, False, None, None, {}))
        s, me = a.get("/api/me")
        check(s == 200 and me.get("role") == "admin" and me.get("username") == "oldadmin", "an old 1.8.1 session still works after migration")
        a = Client()
    s, _ = a.post("/api/login", {"username": "oldadmin", "password": "old-fake-pass-1"})
    if s != 200:     # fresh tree without v181: make an admin
        auth.create_user("oldadmin", "old-fake-pass-1", is_admin=True)
        s, _ = a.post("/api/login", {"username": "oldadmin", "password": "old-fake-pass-1"})
    check(s == 200, "admin signs in")
    raw = a.cookie()
    check(raw and not db.row("SELECT 1 FROM sessions WHERE token=?", (raw,)) and db.row("SELECT 1 FROM sessions WHERE token=?", (auth.token_hash(raw),)),
          "new sessions are stored hashed")

    print("trusted proxies / lockout")
    settings.put("trusted_proxies", "")
    netutil.invalidate()
    H = {"x-forwarded-for": "203.0.113.9", "cf-connecting-ip": "203.0.113.9"}
    check(netutil.client_ip_from("192.0.2.10", H) == "192.0.2.10", "untrusted proxy: forwarded headers ignored")
    settings.put("trusted_proxies", "192.0.2.10")
    netutil.invalidate()
    check(netutil.client_ip_from("192.0.2.10", H) == "203.0.113.9", "trusted proxy: CF-Connecting-IP used")
    check(netutil.client_ip_from("192.0.2.10", {"x-forwarded-for": "198.51.100.7, 203.0.113.50, 192.0.2.10"}) == "203.0.113.50",
          "XFF: right-most untrusted hop")
    check(netutil.client_ip_from("10.9.9.9", H) == "10.9.9.9", "spoofed headers from an untrusted peer are ignored")
    check(netutil.valid_spec("192.0.2.10, 10.0.0.0/8") == [] and netutil.valid_spec("nope") == ["nope"], "spec validation")
    settings.put("trusted_proxies", "")
    netutil.invalidate()
    # the test client connects from 127.0.0.1 which is always trusted, so headers pick the "real" client
    bad = Client({"cf-connecting-ip": "203.0.113.66"})
    codes = [bad.post("/api/login", {"username": "oldadmin", "password": "wrong-%d" % i})[0] for i in range(12)]
    check(codes[-1] == 429, "one client is locked out after repeated failures (%s)" % codes[-3:])
    good = Client({"cf-connecting-ip": "203.0.113.67"})
    check(good.post("/api/login", {"username": "oldadmin", "password": "old-fake-pass-1"})[0] == 200,
          "another client behind the same proxy can still sign in (the lockout bug)")
    useractivity.flush()
    ev = db.row("SELECT * FROM activity WHERE kind='login_failed' ORDER BY id DESC LIMIT 1")
    check(ev and ev["ip"] == "203.0.113.66", "failed sign-ins are logged with the real client IP")

    print("libraries / roles")
    now = int(time.time())
    media = Path(TMP) / "media"
    media.mkdir()
    with db.tx() as c:
        c.execute("INSERT INTO libraries(id,name,kind,path,created_at) VALUES(901,'Family Movies','movies',?,?)", (str(media), now))
        c.execute("INSERT INTO libraries(id,name,kind,path,created_at) VALUES(902,'Private Movies','movies',?,?)", (str(media), now))
        for iid, lib, title in ((5001, 901, "Kid Film"), (5002, 902, "Secret Film")):
            f = media / ("%s.mp4" % iid)
            f.write_bytes(b"\x00" * 4096)
            c.execute("INSERT INTO items(id,library_id,path,media_type,kind,title,sort_title,added_at,probed,size,container,vcodec,acodec,duration) "
                      "VALUES(?,?,?,'video','movie',?,?,?,1,4096,'mp4','h264','aac',60)", (iid, lib, str(f), title, title.lower(), now))
    s, r = a.post("/api/users", {"username": "kidviewer", "password": "fake-pass-kid1", "role": "view", "all_libraries": False,
                                 "libraries": [901], "email": "kid@example.com"})
    check(s == 200, "admin adds a restricted Viewer (%s)" % (r if s != 200 else ""))
    kid = Client()
    check(kid.post("/api/login", {"username": "kid@example.com", "password": "fake-pass-kid1"})[0] == 200, "sign in with email works")
    s, me = kid.get("/api/me")
    check(me.get("role") == "view" and me.get("role_label") == "Viewer" and me.get("all_libraries") in (False, 0), "/api/me shows role + library scope")
    s, libs = kid.get("/api/libraries")
    ids = [l["id"] for l in (libs if isinstance(libs, list) else libs.get("libraries", []))]
    check(901 in ids and 902 not in ids, "restricted user only sees granted libraries (%s)" % ids)
    s, libs = a.get("/api/libraries")
    ids = [l["id"] for l in (libs if isinstance(libs, list) else libs.get("libraries", []))]
    check(901 in ids and 902 in ids, "admin sees every library")
    check(kid.get("/api/items/5002")[0] == 404, "hidden item is 404")
    check(kid.get("/api/items/5002/file")[0] == 404, "hidden item's file is 404")
    check(kid.get("/api/libraries/902")[0] in (404, 405), "hidden library is 404")
    check(kid.get("/api/items/5001")[0] == 200, "granted item opens")
    s, srch = kid.get("/api/search?q=Film")
    check("Secret Film" not in json.dumps(srch) and s == 200, "search never returns hidden titles")
    s, home = kid.get("/api/home")
    check("Secret Film" not in json.dumps(home), "home never shows hidden titles")
    s, srch = a.get("/api/search?q=Film")
    check("Secret Film" in json.dumps(srch), "admin search finds everything")
    check(kid.get("/api/users")[0] == 403 and kid.get("/api/admin/activity")[0] == 403, "viewers can't open admin APIs")
    check(kid.get("/api/items/5001/file?download=1")[0] == 403, "plain file download stays admin-only")

    print("now playing / activity")
    s, _ = kid.get("/api/items/5001/file?player=p1", raw=True)
    check(s in (200, 206), "viewer streams the granted file")
    s, np = a.get("/api/admin/activity/now")
    check(any(n.get("username") == "kidviewer" and (n.get("item") or {}).get("id") == 5001 for n in np.get("now", [])), "Now playing shows the viewer")
    kid.post("/api/items/5001/stop?player=p1", {})
    useractivity.end_player(me["id"], 5001, "p1")
    useractivity.flush()
    s, act = a.get("/api/admin/activity?user=%d" % me["id"])
    kinds = [e["kind"] for e in act.get("events", [])]
    check("login" in kinds and "play_start" in kinds, "timeline has the sign-in and play start (%s)" % kinds[:6])
    check("play_stop" in kinds, "play stop recorded when the player closes")
    s, act = a.get("/api/admin/activity?group=signin")
    check(all(useractivity.KIND_GROUP.get(e["kind"]) == "signin" for e in act["events"]), "group filter")
    useractivity.record("login_failed", actor="=HYPERLINK(\"http://x\")", ip="203.0.113.1")
    useractivity.flush()
    s, body = a.get("/api/admin/activity/export.csv", raw=True)
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    print("    csv head:", rows[:1], "rows:", len(rows))
    check(s == 200 and rows and rows[0][:3] == ["time_utc", "user", "event"], "CSV export has a header")
    check(not any(cell.startswith("=") for r_ in rows for cell in r_), "CSV cells can't start a formula")
    s, mine = kid.get("/api/me/activity")
    check(s == 200 and all(e.get("user_id") in (me["id"], None) for e in mine["events"]), "users see only their own activity")
    with db.tx() as c:
        c.execute("INSERT INTO activity(ts,kind,user_id,ip) VALUES(?,?,?,?)", (now - 200 * 86400, "login", me["id"], "203.0.113.2"))
        c.execute("INSERT INTO activity(ts,kind,user_id,ip) VALUES(?,?,?,?)", (now - 40 * 86400, "login", me["id"], "203.0.113.3"))
        c.execute("INSERT INTO activity(ts,kind,user_id,ip) VALUES(?,?,?,?)", (now - 40 * 86400, "login_failed", None, "203.0.113.4"))
    check(a.put("/api/admin/activity/settings", {"retention_days": 90})[0] == 200, "retention setting saved")
    check(not db.row("SELECT 1 FROM activity WHERE ip='203.0.113.2'"), "events older than retention are pruned")
    r40 = db.row("SELECT ip FROM activity WHERE ts=? AND kind='login'", (now - 40 * 86400,))
    check(r40 and not r40["ip"], "IPs are blanked after 30 days")
    check(not db.row("SELECT 1 FROM activity WHERE kind='login_failed' AND ts=?", (now - 40 * 86400,)), "failed sign-ins kept only 30 days")
    check(a.put("/api/admin/activity/settings", {"retention_days": 12})[0] == 400, "only the offered retention choices")

    print("devices / sessions")
    phone = Client()
    phone.post("/api/login", {"username": "kidviewer", "password": "fake-pass-kid1"})
    s, ss = kid.get("/api/me/sessions")
    lst = ss.get("sessions", ss) if isinstance(ss, dict) else ss
    check(s == 200 and len(lst) >= 2 and any(x.get("current") for x in lst), "device list shows current + other sessions")
    check(all(len(x["id"]) == 16 and "token" not in x for x in lst), "device ids are short hash prefixes, never tokens")
    check(any("Android" in (x.get("device") or "") for x in lst), "device name from user agent (%s)" % [x.get("device") for x in lst])
    other = [x for x in lst if not x.get("current")][0]
    check(kid.delete("/api/me/sessions/%s" % other["id"])[0] == 200, "sign out one device")
    auth.invalidate_cache()
    check(phone.get("/api/me")[0] == 401, "that device is signed out")
    phone.post("/api/login", {"username": "kidviewer", "password": "fake-pass-kid1"})
    check(a.post("/api/users/%d/signout" % me["id"])[0] == 200, "admin: sign out everywhere")
    auth.invalidate_cache()
    check(phone.get("/api/me")[0] == 401 and kid.get("/api/me")[0] == 401, "all the user's sessions ended")
    check(a.put("/api/users/%d" % me["id"], {"disabled": True})[0] == 200, "admin turns the account off")
    check(kid.post("/api/login", {"username": "kidviewer", "password": "fake-pass-kid1"})[0] == 403, "disabled accounts can't sign in")
    a.put("/api/users/%d" % me["id"], {"disabled": False})

    print("invites (no Gmail: copy link)")
    s, inv = a.post("/api/invites", {"email": "friend@example.com", "role": "download", "all_libraries": False, "libraries": [901],
                                      "note": "Hi from the test", "days": 7})
    check(s == 200 and inv.get("sent") is False and "/#/invite/" in inv.get("link", ""), "invite without Gmail returns a link to share")
    tok = inv["link"].rsplit("/", 1)[1]
    check(tok not in db_bytes().decode("latin-1"), "invite token is stored only as a hash")
    row = db.row("SELECT * FROM invites WHERE id=?", (inv["id"],))
    check(abs(row["expires_at"] - (now + 7 * 86400)) < 120, "expires in 7 days")
    s, pv = Client().get("/api/invite/" + tok)
    check(s == 200 and pv.get("email") == "friend@example.com" and "Family Movies" in json.dumps(pv), "anyone with the link sees a preview")
    check(Client().get("/api/invite/" + "x" * 43)[0] == 404, "a made-up token is 404")
    friend = Client()
    s, r = friend.post("/api/invite/%s/accept" % tok, {"username": "friend1", "password": "short"})
    check(s == 400, "password rules on accept")
    s, r = friend.post("/api/invite/%s/accept" % tok, {"username": "friend1", "password": "fake-pass-friend"})
    check(s == 200 and friend.get("/api/me")[1].get("role") == "download", "accepting creates the account with the invite's role and signs in")
    s, libs = friend.get("/api/libraries")
    ids = [l["id"] for l in (libs if isinstance(libs, list) else libs.get("libraries", []))]
    check(ids == [901], "the new account gets the invite's libraries")
    check(Client().post("/api/invite/%s/accept" % tok, {"username": "friend2", "password": "fake-pass-friend"})[0] == 404, "invites work once")
    s, inv2 = a.post("/api/invites", {"email": "late@example.com", "role": "view", "days": 1})
    tok2 = inv2["link"].rsplit("/", 1)[1]
    with db.tx() as c:
        c.execute("UPDATE invites SET expires_at=? WHERE id=?", (now - 5, inv2["id"]))
    check(Client().get("/api/invite/" + tok2)[0] == 404, "expired invites are refused")
    s, inv3 = a.post("/api/invites", {"email": "nope@example.com", "role": "view"})
    tok3 = inv3["link"].rsplit("/", 1)[1]
    check(a.delete("/api/invites/%d" % inv3["id"])[0] == 200 and Client().get("/api/invite/" + tok3)[0] == 404, "revoked invites are refused")
    check(a.post("/api/invites", {"email": "friend@example.com", "role": "view"})[0] == 409, "can't invite an address that already has an account")
    check(a.post("/api/invites", {"email": "not-an-email", "role": "view"})[0] == 400, "email is validated")
    s, inv4 = a.post("/api/invites", {"email": "again@example.com", "role": "view"})
    s, inv5 = a.post("/api/invites", {"email": "again@example.com", "role": "view"})
    st4 = db.row("SELECT revoked_at FROM invites WHERE id=?", (inv4["id"],))
    check(st4["revoked_at"] is not None, "a new invite to the same address replaces the old one")


    print("email with a Gmail app password (mock SMTP)")
    s, es = a.get("/api/settings/email")
    sm = es["smtp"]
    check(es["mail_method"] == "smtp" and sm["status"] == "not_set_up" and sm["provider"] == "gmail",
          "app password (SMTP) is the default method, not set up yet")
    check(sm["suggested_from_name"] == "oldadmin", "From name is prefilled with the user's name when Google's isn't known")
    check(sm["app_password_url"] == "https://myaccount.google.com/apppasswords", "help links to Google app passwords")
    check(a.put("/api/settings/smtp", {"provider": "gmail", "user": "not-an-address", "password": "abcdefghijklmnop"})[0] == 400,
          "Gmail address is validated")
    s, r = a.put("/api/settings/smtp", {"provider": "gmail", "user": mock_smtp.USER, "password": "my normal pass1"})
    check(s == 400 and "16 letters" in json.dumps(r), "a normal Gmail password is refused with a hint")
    s, es = a.put("/api/settings/smtp", {"provider": "gmail", "user": mock_smtp.USER, "password": "abcd efgh ijkl mnop", "from_name": "Test Host"})
    sm = es.get("smtp", {})
    check(s == 200 and sm.get("configured") and sm.get("password_saved") and sm.get("status") == "untested", "address + app password saved (spaces ignored)")
    check(mock_smtp.PASSWORD not in json.dumps(es) and "abcd efgh" not in json.dumps(es), "the password is never returned")
    check(mock_smtp.PASSWORD.encode() not in db_bytes() and b"abcd efgh" not in db_bytes(), "the password is encrypted at rest")
    sp = keys.SECRETS_DIR / "smtp.sealed"
    check(sp.is_file() and stat.S_IMODE(sp.stat().st_mode) == 0o600, "smtp.sealed is mode 600")
    check(sm.get("host") == "localhost" and sm.get("security") == "starttls" and sm.get("from_addr") == mock_smtp.USER,
          "Gmail uses STARTTLS and the From address is the Gmail address")
    s, ms = a.get("/api/mail/status")
    check(ms.get("ready") and ms.get("from_name") == "Test Host" and ms.get("from_addr") == mock_smtp.USER, "/api/mail/status for the invite dialog")
    n0 = len(SMTP_TLS.received)
    s, r = a.post("/api/smtp/test")
    check(s == 200 and r.get("to") == mock_smtp.USER and len(SMTP_TLS.received) == n0 + 1, "Test sends one email to yourself")
    got = SMTP_TLS.received[-1]
    check(got["tls"] and got["user"] == mock_smtp.USER and got["from"] == mock_smtp.USER and got["to"] == [mock_smtp.USER],
          "sent over STARTTLS after signing in, envelope from/to the Gmail address")
    m = email.message_from_bytes(got["data"], policy=email.policy.default)
    check(str(m["From"]) == "Test Host <%s>" % mock_smtp.USER and str(m["Reply-To"]) == str(m["From"]), "From and Reply-To are \"Test Host <gmail address>\"")
    check(str(m["Subject"]).startswith("[Test] Test invited you"), "test subject (%s)" % m["Subject"])
    check(a.get("/api/settings/email")[1]["smtp"]["status"] == "ok", "status becomes Working after a good send")

    n0 = len(SMTP_TLS.received)
    s, inv_s = a.post("/api/invites", {"email": "smtp.friend@example.com", "role": "view", "note": "Hello\r\nBcc: evil@example.com", "days": 7})
    check(s == 200 and inv_s.get("sent") is True and inv_s.get("via") == "smtp" and inv_s.get("from") == mock_smtp.USER, "invite emailed with the app password")
    got = SMTP_TLS.received[-1]
    m = email.message_from_bytes(got["data"], policy=email.policy.default)
    check(got["to"] == ["smtp.friend@example.com"] and str(m["To"]) == "smtp.friend@example.com", "To is the invitee")
    check(m.get_content_type() == "multipart/alternative" and [p_.get_content_type() for p_ in m.iter_parts()] == ["text/plain", "text/html"],
          "plain text + HTML")
    check(inv_s["link"] in m.get_body(("plain",)).get_content() and inv_s["link"] in m.get_body(("html",)).get_content(), "the link is in both parts")
    check(m["Bcc"] is None and not any("evil@example.com" in str(v) for v in m.values()), "the note can't add headers")
    row = db.row("SELECT sent_via FROM invites WHERE id=?", (inv_s["id"],))
    check(row["sent_via"] == "email", "invite marked as emailed")
    a.put("/api/settings/smtp", {"from_name": "Evil\r\nBcc: x@example.com"})
    a.post("/api/invites", {"email": "inj@example.com", "role": "view"})
    m = email.message_from_bytes(SMTP_TLS.received[-1]["data"], policy=email.policy.default)
    check(m["Bcc"] is None and "\n" not in str(m["From"]), "a From name with CR/LF can't add headers (%s)" % m["From"])
    a.put("/api/settings/smtp", {"from_name": "Test Host"})

    print("SMTP errors and limits")
    a.put("/api/settings/smtp", {"password": "zzzzzzzzzzzzzzzz"})
    s, r = a.post("/api/smtp/test")
    check(s == 400 and "535" in json.dumps(r) and "apppasswords" in json.dumps(r), "wrong app password (535) explained")
    check(a.get("/api/settings/email")[1]["smtp"]["status"] == "auth_failed", "status shows the problem")
    s, r = a.post("/api/invites", {"email": "badpw@example.com", "role": "view"})
    check(r.get("sent") is False and r.get("reconnect") and r.get("link"), "with a bad password the invite falls back to the link")
    a.put("/api/settings/smtp", {"password": mock_smtp.PASSWORD})
    SMTP_TLS.fail["auth"] = "534-5.7.9 Application-specific password required.\r\n534 5.7.9 mock"
    s, r = a.post("/api/smtp/test")
    SMTP_TLS.fail.pop("auth", None)
    check(s == 400 and "2-Step Verification" in json.dumps(r), "534 app-password-required explained")
    SMTP_TLS.fail["mail"] = ["421 4.7.0 Try again later, closing connection."]
    s, r = a.post("/api/invites", {"email": "retry2@example.com", "role": "view"})
    check(r.get("sent") is True, "a 421 rate limit is retried with backoff")
    SMTP_TLS.fail["mail"] = ["421 4.7.0 Try again later"] * 4
    s, r = a.post("/api/invites", {"email": "busy@example.com", "role": "view"})
    SMTP_TLS.fail.pop("mail", None)
    check(r.get("sent") is False and "try later" in (r.get("error") or "") and r.get("link"), "persistent 421: link fallback (%s)" % r.get("error"))
    SMTP_TLS.fail["data"] = ["550 5.4.5 Daily user sending limit exceeded."]
    s, r = a.post("/api/invites", {"email": "daily@example.com", "role": "view"})
    SMTP_TLS.fail.pop("data", None)
    check(r.get("sent") is False and "daily sending limit" in (r.get("error") or ""), "Gmail daily limit (550 5.4.5) explained")
    SMTP_TLS.fail["rcpt"] = ["550 5.1.1 The email account that you tried to reach does not exist."]
    s, r = a.post("/api/invites", {"email": "nobody@example.com", "role": "view"})
    SMTP_TLS.fail.pop("rcpt", None)
    check(r.get("sent") is False and "refused that email address" in (r.get("error") or ""), "unknown recipient explained")
    now2 = int(time.time())
    with db.tx() as c:
        c.execute("DELETE FROM gmail_sends WHERE user_id=0")
        for i in range(20):
            c.execute("INSERT INTO gmail_sends(user_id, ts) VALUES(0,?)", (now2 - 30,))
    s, r = a.post("/api/invites", {"email": "cap2@example.com", "role": "view"})
    check(r.get("sent") is False and "20 invites an hour" in (r.get("error") or "") and r.get("link"), "the 21st email in an hour falls back to the link")
    check(a.post("/api/smtp/test")[0] == 400, "the test email counts toward the cap too")
    with db.tx() as c:
        c.execute("DELETE FROM gmail_sends WHERE user_id=0")

    print("generic SMTP")
    s, es = a.put("/api/settings/smtp", {"provider": "custom", "host": "localhost", "port": SMTP_SSL.port, "security": "ssl",
                                         "user": mock_smtp.USER, "password": mock_smtp.PASSWORD, "from_addr": "movies@example.com", "from_name": "Movie Night"})
    check(s == 200 and es["smtp"]["provider"] == "custom" and es["smtp"]["security"] == "ssl", "generic SMTP saved (SSL/TLS)")
    s, r = a.post("/api/smtp/test")
    got = SMTP_SSL.received[-1] if SMTP_SSL.received else {}
    m = email.message_from_bytes(got.get("data", b""), policy=email.policy.default)
    check(s == 200 and got.get("tls") and str(m["From"]) == "Movie Night <movies@example.com>", "generic SMTP over SSL/TLS sends with its From address")
    check(a.put("/api/settings/smtp", {"provider": "custom", "host": "bad host!", "port": 25, "security": "none"})[0] == 400, "host is validated")
    check(a.put("/api/settings/smtp", {"provider": "custom", "host": "localhost", "port": 0})[0] == 400, "port is validated")
    s, es = a.put("/api/settings/smtp", {"provider": "custom", "host": "127.0.0.1", "port": SMTP_PLAIN.port, "security": "none",
                                         "user": "", "from_addr": "relay@example.com"})
    s, r = a.post("/api/smtp/test")
    check(s == 200 and SMTP_PLAIN.received and SMTP_PLAIN.received[-1]["user"] is None, "a LAN relay without sign-in works")
    dead = socket.socket(); dead.bind(("127.0.0.1", 0)); dport = dead.getsockname()[1]; dead.close()
    a.put("/api/settings/smtp", {"provider": "custom", "host": "127.0.0.1", "port": dport, "security": "none", "user": "", "from_addr": "relay@example.com"})
    s, r = a.post("/api/smtp/test")
    check(s == 400 and "Couldn't connect" in json.dumps(r), "unreachable server explained")
    SMTP_SSL.fail["auth"] = None
    a.put("/api/settings/smtp", {"provider": "custom", "host": "localhost", "port": SMTP_TLS.port, "security": "ssl", "user": mock_smtp.USER,
                                 "password": mock_smtp.PASSWORD, "from_addr": mock_smtp.USER})
    s, r = a.post("/api/smtp/test")
    check(s == 400 and ("Secure connection" in json.dumps(r) or "closed the connection" in json.dumps(r)), "wrong security for the port explained (%s)" % json.dumps(r)[:120])
    s, es = a.delete("/api/settings/smtp")
    check(s == 200 and es["smtp"]["status"] == "not_set_up" and not (keys.SECRETS_DIR / "smtp.sealed").exists(), "Remove deletes the saved password")
    useractivity.flush()
    alltext = LOGBUF.getvalue() + json.dumps([dict(r_) for r_ in db.rows("SELECT * FROM activity")]) + json.dumps([dict(r_) for r_ in db.rows("SELECT * FROM settings")])
    check(mock_smtp.PASSWORD not in alltext and "zzzzzzzzzzzzzzzz" not in alltext, "no password in logs, activity or settings")
    check("email_test" in alltext and "email_error" in alltext, "email test and problems are in the activity log")
    print("Connect Gmail (mock Google)")
    s, es = a.get("/api/settings/email")
    check(es.get("paste_redirect_uri") == "http://localhost/movinite-gmail-callback" and es["redirect_uri"].endswith("/api/gmail/callback"),
          "Settings > Email shows both redirect URIs")
    check(es["hourly_cap"] == 20 and es["daily_cap"] == 100, "caps default to 20/hour and 100/day")
    check(a.put("/api/settings/email", {"client_id": "not-a-client"})[0] == 400, "client id is validated")
    s, es = a.put("/api/settings/email", {"client_id": mock_google.CLIENT_ID, "client_secret": mock_google.CLIENT_SECRET})
    check(s == 200 and es["client_secret_saved"] and "client_secret" not in json.dumps(es).replace("client_secret_saved", ""),
          "client secret saved and never returned")
    check(mock_google.CLIENT_SECRET.encode() not in db_bytes(), "client secret is encrypted at rest (not in any data file)")
    sealed = keys.SECRETS_DIR / "gmail.sealed"
    check(sealed.is_file() and stat.S_IMODE(sealed.stat().st_mode) == 0o600, "gmail.sealed is mode 600")

    s, st = a.post("/api/gmail/connect", {"paste": True})
    check(s == 200 and st["redirect_uri"] == gmail.PASTE_REDIRECT, "paste-mode connect")
    q = urllib.parse.urlparse(st["url"]).query
    qd = dict(urllib.parse.parse_qsl(q))
    check(set(qd["scope"].split()) == {"openid", "email", "profile", gmail.SEND_SCOPE}, "scopes: openid email profile gmail.send")
    check(qd["code_challenge_method"] == "S256" and qd["access_type"] == "offline" and qd["prompt"] == "consent", "PKCE S256, offline, consent")
    landed = mock_google.authorize(q)
    # a different admin session can't finish this sign-in
    b = Client()
    b.post("/api/login", {"username": "oldadmin", "password": "old-fake-pass-1"})
    s, r = b.post("/api/gmail/paste", {"url": landed})
    check(s == 400 and "different session" in json.dumps(r), "state is bound to the session that started it")
    s, st = a.post("/api/gmail/connect", {"paste": True})
    q = urllib.parse.urlparse(st["url"]).query
    landed = mock_google.authorize(q)
    s, st = a.post("/api/gmail/paste", {"url": landed})
    check(s == 200 and st.get("status") == "connected" and st.get("email") == mock_google.TEST_EMAIL, "pasting the address connects Gmail")
    check(st.get("display_name") == mock_google.TEST_NAME, "the From name is the Google profile name")
    check(a.get("/api/settings/email")[1]["mail_method"] == "gmail_oauth", "connecting Gmail with nothing else set up selects it")
    check(a.get("/api/settings/email")[1]["smtp"]["suggested_from_name"] == mock_google.TEST_NAME, "the app-password From name now defaults to the Google name")
    check(a.post("/api/gmail/paste", {"url": landed})[0] == 400, "a state can't be reused")
    tokens_seen = list(mock_google.STATE["refresh"].keys())
    blob = db_bytes()
    check(tokens_seen and not any(t.encode() in blob for t in tokens_seen), "refresh token is encrypted at rest")
    check(b"ya29.mock-access" not in blob, "access tokens are never written to disk")

    # a sign-in that unticks the send permission is refused
    s, st = a.post("/api/gmail/connect", {"paste": True})
    mock_google.STATE["granted_scope"] = "openid email profile"
    landed = mock_google.authorize(urllib.parse.urlparse(st["url"]).query)
    mock_google.STATE["granted_scope"] = None
    s, r = a.post("/api/gmail/paste", {"url": landed})
    check(s == 400 and "send email" in json.dumps(r), "missing gmail.send scope is refused")
    check(a.get("/api/gmail/status")[1]["status"] == "connected", "the earlier connection is kept")

    print("sending an invite through Gmail (mock)")
    mock_google.STATE["sent"].clear()
    s, inv6 = a.post("/api/invites", {"email": "friend.test@example.com", "role": "view", "note": "Line one\r\nBcc: evil@example.com", "days": 7})
    check(s == 200 and inv6.get("sent") is True and inv6.get("via") == "gmail_oauth", "invite sent through Connect Gmail when it's the chosen method")
    check(len(mock_google.STATE["sent"]) == 1, "exactly one message hit the Gmail API")
    m = email.message_from_bytes(mock_google.STATE["sent"][0], policy=email.policy.default)
    check(str(m["From"]) == "%s <%s>" % (mock_google.TEST_NAME, mock_google.TEST_EMAIL), "From is \"Test Host <test.host@example.com>\" (%s)" % m["From"])
    check(str(m["Reply-To"]) == str(m["From"]) and str(m["To"]) == "friend.test@example.com", "Reply-To and To")
    check(m["Bcc"] is None and "evil@example.com" not in str(m.items()), "the note can't inject headers")
    check(str(m["Subject"]) == "Test invited you to their Movinite", "subject uses the first name (%s)" % m["Subject"])
    check(m.get_content_type() == "multipart/alternative", "multipart/alternative")
    parts = [p.get_content_type() for p in m.iter_parts()]
    check(parts == ["text/plain", "text/html"], "text then HTML (%s)" % parts)
    txt = m.get_body(("plain",)).get_content()
    htm = m.get_body(("html",)).get_content()
    link = inv6["link"]
    check(link in txt and link in htm, "the link is in both parts")
    check("expires on" in txt and "works once" in txt, "expiry and one-time use explained")
    check("Line one" in txt and "&lt;" not in txt and "<script" not in htm, "note included")
    hdr = gmail.build_message("Evil\r\nBcc: x@example.com", mock_google.TEST_EMAIL, "a@example.com", "S\nX-Bad: 1", "t", "<p>h</p>")
    check(hdr["Bcc"] is None and hdr["X-Bad"] is None and "\n" not in str(hdr["Subject"]), "build_message strips CR/LF from headers")
    try:
        gmail.build_message("A", mock_google.TEST_EMAIL, "a@example.com\r\nCc: y@example.com", "S", "t", "<p>h</p>")
        check(False, "an address with a header in it is refused")
    except gmail.GmailError:
        check(True, "an address with a header in it is refused")

    print("caps, retries, expired sign-in, disconnect")
    with db.tx() as c:
        for i in range(19):
            c.execute("INSERT INTO gmail_sends(user_id, ts) VALUES(?,?)", (st_uid := db.row("SELECT id FROM users WHERE username='oldadmin'")["id"], now - 60))
    sh, sd = gmail._counts(st_uid)
    check(sh == 20, "20 sends in the last hour (%d)" % sh)
    s, inv7 = a.post("/api/invites", {"email": "cap@example.com", "role": "view"})
    check(s == 200 and inv7["sent"] is False and "20 invites an hour" in (inv7.get("error") or "") and inv7.get("link"),
          "the 21st invite in an hour falls back to the link (%s)" % inv7.get("error"))
    with db.tx() as c:
        c.execute("UPDATE gmail_sends SET ts=? WHERE user_id=?", (now - 7200, st_uid))
    mock_google.FAIL["send"] = [(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Rate"}}),
                                (503, {"error": {"code": 503, "message": "busy"}})]
    s, inv8 = a.post("/api/invites", {"email": "retry@example.com", "role": "view"})
    check(inv8.get("sent") is True, "429/503 are retried with backoff")
    gmail._access.clear()
    mock_google.FAIL["refresh"] = "invalid_grant"
    s, inv9 = a.post("/api/invites", {"email": "expired@example.com", "role": "view"})
    mock_google.FAIL.pop("refresh", None)
    check(inv9.get("sent") is False and inv9.get("reconnect") and inv9.get("link"), "an expired Google sign-in falls back to the link")
    check(a.get("/api/gmail/status")[1]["status"] == "needs_reconnect", "status says reconnect")
    # reconnect, then disconnect revokes at Google
    s, st = a.post("/api/gmail/connect", {"paste": True})
    s, st = a.post("/api/gmail/paste", {"url": mock_google.authorize(urllib.parse.urlparse(st["url"]).query)})
    check(st.get("status") == "connected", "reconnect works")
    rt = gmail._refresh_token(st_uid)
    s, r = a.delete("/api/gmail")
    check(s == 200 and r["revoked"] and rt in mock_google.STATE["revoked"], "disconnect revokes the token at Google")
    check(gmail._refresh_token(st_uid) is None, "and deletes it")
    s, inv10 = a.post("/api/invites", {"email": "after@example.com", "role": "view"})
    check(inv10["sent"] is False and inv10.get("link"), "after disconnect invites use the link")
    useractivity.flush()
    kinds = {r_["kind"] for r_ in db.rows("SELECT kind FROM activity")}
    check({"gmail_connected", "gmail_disconnected", "invite_sent", "invite_accepted", "invite_send_failed"} <= kinds,
          "Gmail and invite events are in the activity log")
    details = " ".join((r_["detail"] or "") for r_ in db.rows("SELECT detail FROM activity"))
    check(mock_google.CLIENT_SECRET not in details and "mock-refresh" not in details, "no secrets in activity details")
    s, es = a.put("/api/settings/email", {"client_id": "999-other.apps.googleusercontent.com"})
    check(s == 200, "changing the OAuth client is allowed")

    print("user admin guards")
    check(a.put("/api/users/%d" % st_uid, {"role": "view"})[0] == 400, "can't remove your own admin role")
    check(a.delete("/api/users/%d" % st_uid)[0] in (400, 409), "can't delete the last admin / yourself")
    s, users = a.get("/api/users")
    lst = users.get("users", users) if isinstance(users, dict) else users
    check(any(x["username"] == "friend1" and x["role"] == "download" and x["libraries"] == [901] for x in lst), "Users lists role and libraries")

    print()
    if fails:
        print("FAILED %d:" % len(fails))
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("all 1.9 checks passed")


if __name__ == "__main__":
    main()
