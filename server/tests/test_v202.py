"""2.0.2: TV phone-code pairing, stay-signed-in sliding sessions, LAN discovery docs.

    python3 tests/test_v202.py

Made-up logins only. Nothing leaves 127.0.0.1.
"""
import json
import os
import sqlite3
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
TMP = tempfile.mkdtemp(prefix="ms-v202-")
DATA = TMP + "/data"
os.environ["MS_DATA_DIR"] = DATA
os.environ["MS_SESSION_DAYS"] = "30"

from app import auth, db, discover, pair, server  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
db_src = (ROOT / "app/db.py").read_text()

print("version and docs")
check(__version__ == "2.0.2", "version is 2.0.2 (%s)" % __version__)
check("SCHEMA_VERSION = 11" in db_src, "SCHEMA_VERSION stays 11")
check("CREATE TABLE IF NOT EXISTS pair_codes" in db_src, "pair_codes is created idempotently")
check("pre-schema12" not in db_src, "no pre-schema12 snapshot (2.1 can still be 12)")
check("## 2.0.2" in ch and ch.find("## 2.0.2") < ch.find("## 2.0.1"), "CHANGELOG has 2.0.2 above 2.0.1")
check("schema stays 11" in ch.lower() or "Schema stays 11" in ch, "changelog notes schema stays 11")
check("does **not** show the code-and-QR" in ch or "does not show the code-and-QR" in ch.lower()
      or "never loads the web page" in ch, "changelog says the 2.0 APK needs an update for pairing")
check("Easier TV sign-in (2.0.2)" in rd, "README has a 2.0.2 sign-in section")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
check("/pair?code=" in rd, "README shows the /pair?code= URL")

print("source: pairing, stay signed in, discovery")
check("function showTvPairLogin" in js and "function showPairApprove" in js, "TV pair + phone approve UI exist")
check('id="pairf"' in js and 'id="loginf"' in js, "pairing screen is #pairf; password form stays #loginf")
check("startTvPair" in js and "/api/pair/start" in js and "/api/pair/poll" in js, "TV starts a code and polls")
check("MSQR.svg" in js, "QR uses the existing QR helper")
check("This TV stays signed in" in js, "stay-signed-in copy on the TV screen")
check("msRecentServers" in js and "/.well-known/movinite.json" in js, "JS remembers and probes recent servers")
check("Approve this TV" in js or "Approve this TV?" in js, "approval page titles the action")
check("pair-device" in js, "approval page names the device")
check("TV.init()" in js[js.find("function focusAuth"):js.find("function focusAuth")+400],
      "TV remote is bound on the sign-in screens")
check("expires_at=?" in (ROOT / "app/auth.py").read_text() or "expires_at=?" in open(ROOT / "app/auth.py").read(),
      "sessions slide expires_at on use")
check("_movinite._tcp" in (ROOT / "app/discover.py").read_text(), "mDNS service type is _movinite._tcp")
check("zeroconf" in (ROOT / "requirements.txt").read_text(), "zeroconf is in requirements")
check("pair-code" in css and "auth-tv-pair" in css, "pairing screen CSS is present")
check("headerItems" in js and "acctMenuOpen" in js and "isTopContentRow" in js, "TV header / account-menu helpers exist")
check('"#logout"' in js and "acct-page-logout" in js, "sidebar Sign out and Settings > My account Sign out are candidates")
check("html.tv-mode .acct-w" in css, "TV mode shows the header account button")
check("account button" in ch.lower() and "Sign out" in ch.split("## 2.0.1")[0], "changelog mentions remote Sign out / account button")

# Alphabet has no ambiguous characters
check(pair.ALPHABET == "ABCDEFGHJKMNPQRSTUVWXYZ23456789", "code alphabet omits 0/O/1/I/L")
check("0" not in pair.ALPHABET and "O" not in pair.ALPHABET and "1" not in pair.ALPHABET
      and "I" not in pair.ALPHABET and "L" not in pair.ALPHABET, "no ambiguous characters in the alphabet")

PORT = 19200 + os.getpid() % 400
BASE = "http://127.0.0.1:%d" % PORT

db.migrate()
auth.create_user("admin", "TestPass14!", is_admin=True)
auth.create_user("viewer", "TestView14!", is_admin=False)

# schema 11 + table exists; no pre-schema12 backup
meta = db.row("SELECT value FROM meta WHERE key='schema_version'")
check(meta and meta["value"] == "11", "migrate leaves schema_version at 11 (got %s)" % (meta and meta["value"]))
cols = {r[1] for r in db.get().execute("PRAGMA table_info(pair_codes)")}
check("code_hash" in cols and "poll_hash" in cols and "status" in cols and "device" in cols,
      "pair_codes has the expected columns")
check(not (Path(DATA) / "media-server.db.pre-schema12").exists(), "no pre-schema12 backup file was written")

import uvicorn  # noqa: E402
t = threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                     daemon=True)
t.start()
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=0.3).read()
        break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit("test server did not start")


def req(path, method="GET", data=None, cookies=None, ua=None, headers=None, origin=None):
    h = {"Accept": "application/json"}
    if ua:
        h["User-Agent"] = ua
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=h)
    cj = cookies if cookies is not None else CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        with opener.open(r, timeout=8) as resp:
            raw = resp.read()
            ct = resp.headers.get("content-type") or ""
            jsout = json.loads(raw.decode()) if "json" in ct else raw.decode()
            return resp.status, jsout, cj, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            jsout = json.loads(raw.decode())
        except Exception:
            jsout = raw.decode()
        return e.code, jsout, cj, dict(e.headers)


TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.0 AndroidTV")
PHONE_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 MediaServerAndroid/2.0"


def login(user, pw, ua=PHONE_UA):
    cj = CookieJar()
    st, body, cj, _ = req("/api/login", "POST", {"username": user, "password": pw}, cookies=cj, ua=ua)
    check(st == 200, "login %s -> %s" % (user, st))
    return cj


print("discovery endpoint")
st, body, _, _ = req("/.well-known/movinite.json")
check(st == 200 and body.get("service") == "movinite" and body.get("version") == "2.0.2",
      "well-known movinite.json identifies this server (%s)" % body)
st, health, _, _ = req("/api/health")
check(st == 200 and health.get("version") == "2.0.2", "health reports 2.0.2")

print("pair start / poll / approve")
st, started, tv_cj, _ = req("/api/pair/start", "POST", {}, ua=TV_UA)
check(st == 200 and started.get("code") and started.get("poll_token"), "POST /api/pair/start returns a code and poll token")
check(started.get("display") and "-" in started["display"], "code is shown as XXX-XXX (%s)" % started.get("display"))
check(len(pair.normalize(started["code"])) == 6, "code is 6 characters")
check(all(ch in pair.ALPHABET for ch in started["code"]), "code uses the safe alphabet")
check(started.get("url", "").endswith("/pair?code=" + started["code"]), "QR URL is /pair?code=XXXXXX")
check("TV" in (started.get("device") or "") or "Movinite" in (started.get("device") or ""),
      "device name from the TV user-agent (%s)" % started.get("device"))
check(started.get("expires_in", 0) >= 9 * 60, "code lasts about 10 minutes (%s s)" % started.get("expires_in"))

st, polled, _, _ = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA, cookies=tv_cj)
check(st == 200 and polled.get("status") == "pending", "poll is pending before approval (%s)" % polled)

# unauthenticated info/approve is rejected
st, _, _, _ = req("/api/pair/info?code=" + started["code"])
check(st == 401, "pair info requires sign-in (%s)" % st)
st, _, _, _ = req("/api/pair/approve", "POST", {"code": started["code"]})
check(st == 401, "pair approve requires sign-in (%s)" % st)

phone = login("admin", "TestPass14!")
st, info, _, _ = req("/api/pair/info?code=" + started["code"], cookies=phone, ua=PHONE_UA)
check(st == 200 and info.get("device") and "admin" in (info.get("username") or ""),
      "info names the device and the signed-in user (%s)" % info)
# typo / hyphenated display form should work
st, _, _, _ = req("/api/pair/approve", "POST", {"code": started["display"]}, cookies=phone, ua=PHONE_UA)
check(st == 200, "approve accepts the displayed XXX-XXX form")

st, polled, tv_cj, hdrs = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA, cookies=tv_cj)
check(st == 200 and polled.get("status") == "approved", "poll becomes approved and returns a session")
setc = hdrs.get("Set-Cookie") or hdrs.get("set-cookie") or ""
check("ms_session=" in setc, "approved poll sets the ms_session cookie")
st, me, _, _ = req("/api/me", cookies=tv_cj, ua=TV_UA)
check(st == 200 and me.get("username") == "admin", "TV session is signed in as the approving user (%s)" % me)

# single-use
st, again, _, _ = req("/api/pair/approve", "POST", {"code": started["code"]}, cookies=phone, ua=PHONE_UA)
check(st in (409, 404), "a used code cannot be approved again (%s)" % st)
st, polled2, _, _ = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA)
check(st == 200 and polled2.get("status") in ("consumed", "unknown"),
      "a second poll after redeem is consumed/unknown (%s)" % polled2)

# bad / expired codes
st, started2, _, _ = req("/api/pair/start", "POST", {}, ua=TV_UA)
# expire it in the db
db.get().execute("UPDATE pair_codes SET expires_at=? WHERE poll_hash=?",
                 (int(time.time()) - 1, pair._hash("poll", started2["poll_token"])))
db.get().commit()
st, polled, _, _ = req("/api/pair/poll", "POST", {"token": started2["poll_token"]}, ua=TV_UA)
check(st == 200 and polled.get("status") == "expired", "poll reports expired after the TTL (%s)" % polled)
st, _, _, _ = req("/api/pair/info?code=" + started2["code"], cookies=phone, ua=PHONE_UA)
check(st == 404, "info for an expired code is 404")

# deny
st, started3, tv3, _ = req("/api/pair/start", "POST", {}, ua=TV_UA)
st, _, _, _ = req("/api/pair/deny", "POST", {"code": started3["code"]}, cookies=phone, ua=PHONE_UA)
check(st == 200, "signed-in user can deny a code")
st, polled, _, _ = req("/api/pair/poll", "POST", {"token": started3["poll_token"]}, ua=TV_UA, cookies=tv3)
check(st == 200 and polled.get("status") == "denied", "poll reports denied")

# rate limit on start
hit = 0
last = 200
for i in range(12):
    st, _, _, _ = req("/api/pair/start", "POST", {}, ua=TV_UA)
    last = st
    if st == 429:
        hit += 1
        break
check(hit == 1 and last == 429, "starting too many codes is rate-limited (429)")

print("stay signed in")
# set this session close to expiry, then hit /api/me and expect a slide
tok_row = db.row("SELECT token, expires_at FROM sessions ORDER BY last_seen DESC LIMIT 1")
old_exp = int(time.time()) + 60
db.get().execute("UPDATE sessions SET expires_at=? WHERE token=?", (old_exp, tok_row["token"]))
db.get().commit()
# clear auth cache
auth.invalidate_cache()
# force last_seen old enough to trigger the update
db.get().execute("UPDATE sessions SET last_seen=? WHERE token=?", (int(time.time()) - 400, tok_row["token"]))
db.get().commit()
st, me, _, _ = req("/api/me", cookies=phone, ua=PHONE_UA)
check(st == 200, "/api/me still works on a near-expiry session")
row = db.row("SELECT expires_at FROM sessions WHERE token=?", (tok_row["token"],))
check(row and row["expires_at"] > int(time.time()) + 20 * 86400,
      "expires_at slides forward on use (now %s, was %s)" % (row and row["expires_at"], old_exp))

print("logout still works")
st, _, tv_cj, _ = req("/api/logout", "POST", {}, cookies=tv_cj, ua=TV_UA)
st, me, _, _ = req("/api/me", cookies=tv_cj, ua=TV_UA)
check(st == 401, "sign-out ends the TV session")

# /pair is served as the SPA (not a raw 404)
st, html, _, hdrs = req("/pair?code=ABC123")
# our req() assumes json — 200 HTML may parse-fail into a string
# reopen as text
try:
    with urllib.request.urlopen(BASE + "/pair?code=ABC123", timeout=8) as resp:
        raw = resp.read().decode()
        code = resp.status
except urllib.error.HTTPError as e:
    raw, code = e.read().decode(), e.code
check(code == 200 and "<!doctype html" in raw.lower() and "app.js" in raw, "/pair?code= serves the app page")

print()
if fails:
    print("%d failed:" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("all tests passed")
