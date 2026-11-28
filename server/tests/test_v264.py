"""2.6.4: login and approved pair poll return the session token in the JSON body."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v264-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)


from app.version import __version__
from app import auth, db, pair, server  # noqa: E402
import uvicorn

ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
srv = (ROOT / "app/server.py").read_text()

print("version and docs")
check(__version__ == "2.6.4", "version is 2.6.4, got %s" % __version__)
check("## 2.6.4" in ch and ch.find("## 2.6.4") < ch.find("## 2.6.3"), "CHANGELOG has 2.6.4 above 2.6.3")
sec = ch.split("## 2.6.4", 1)[1].split("## 2.6.3", 1)[0]
check("token" in sec.lower() and "json" in sec.lower(), "CHANGELOG 2.6.4 mentions the JSON token")
check("Roku" in sec and "Set-Cookie" in sec or "cookie" in sec.lower(), "CHANGELOG 2.6.4 mentions Roku / cookie")
check("no new android" in sec.lower() or "no new Android" in sec, "CHANGELOG notes no new Android app")
check("**2.6.4:**" in rd, "install README mentions 2.6.4")
check('r.pop("token"' not in srv, "poll no longer pops token from the JSON")
check('r.get("token")' in srv, "poll still reads token to set the cookie")
check('"token": tok' in srv, "login JSON includes token")
for bad in ("192.168.", "tukuia.com password", "ms_session=secret"):
    check(bad not in sec, "2.6.4 changelog does not contain %r" % bad)

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)
auth.create_user("admin", "TestPass14!", is_admin=True)

# local server
sock_err = []


def _run():
    try:
        uvicorn.run(server.app, host="127.0.0.1", port=18099, log_level="error", access_log=False)
    except Exception as e:
        sock_err.append(e)


th = threading.Thread(target=_run, daemon=True)
th.start()
deadline = time.time() + 8
while time.time() < deadline:
    try:
        urllib.request.urlopen("http://127.0.0.1:18099/api/health", timeout=0.4)
        break
    except Exception:
        time.sleep(0.1)
else:
    check(False, "test server did not start: %s" % (sock_err or "timeout"))
    sys.exit(1)


def req(path, method="GET", data=None, cookies=None, ua=None, headers=None):
    h = {"Content-Type": "application/json", "User-Agent": ua or "Movinite-Roku/0.1.4 test"}
    if headers:
        h.update(headers)
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request("http://127.0.0.1:18099" + path, data=body, headers=h, method=method)
    if cookies is not None:
        cookies.add_cookie_header(r)
    try:
        with urllib.request.urlopen(r, timeout=8) as resp:
            raw = resp.read()
            hdrs = dict(resp.headers.items())
            if cookies is not None:
                cookies.extract_cookies(resp, r)
            try:
                parsed = json.loads(raw.decode() or "null")
            except Exception:
                parsed = raw.decode()
            return resp.status, parsed, cookies, hdrs
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw.decode() or "null")
        except Exception:
            parsed = raw.decode()
        return e.code, parsed, cookies, dict(e.headers.items())


print("password login returns token in JSON and a cookie")
cj = CookieJar()
st, body, cj, hdrs = req("/api/login", "POST", {"username": "admin", "password": "TestPass14!"}, cookies=cj)
check(st == 200 and body.get("ok") is True, "POST /api/login 200 ok")
tok = body.get("token") or ""
check(isinstance(tok, str) and len(tok) >= 16, "login JSON includes a session token")
check(body.get("username") == "admin", "login JSON includes username")
setc = hdrs.get("Set-Cookie") or hdrs.get("set-cookie") or ""
check("ms_session=" in setc, "login still sets the ms_session cookie")
# cookie value should match JSON token
check(("ms_session=" + tok) in setc.replace(" ", ""), "JSON token matches the cookie")
st, me, _, _ = req("/api/me", cookies=cj)
check(st == 200 and me.get("username") == "admin", "cookie session works after login")
# Bearer from the JSON token also works (Roku path)
st, me2, _, _ = req("/api/me", headers={"Authorization": "Bearer " + tok}, ua="Movinite-Roku/0.1.4 test")
check(st == 200 and me2.get("username") == "admin", "Bearer token from login JSON works")

print("approved pair poll returns token in JSON and a cookie")
pair._hits.clear()
pair._live.clear()
TV_UA = "Movinite-Roku/0.1.4 (Roku 3810X; 16.0.4)"
st, started, _, _ = req("/api/pair/start", "POST", {}, ua=TV_UA)
check(st == 200 and started.get("code") and started.get("poll_token"), "pair/start returns a code")
check(started.get("url", "").endswith("/pair?code=" + started["code"]), "QR URL is /pair?code=XXXXXX")
st, polled, _, _ = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA)
check(st == 200 and polled.get("status") == "pending", "poll is pending before approval")
# approve with the already-signed-in admin cookie
st, _, _, _ = req("/api/pair/approve", "POST", {"code": started["code"]}, cookies=cj, ua="Mozilla/5.0 phone")
check(st == 200, "phone can approve the code")
tv_cj = CookieJar()
st, polled, tv_cj, hdrs = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA, cookies=tv_cj)
check(st == 200 and polled.get("status") == "approved", "poll becomes approved")
ptok = polled.get("token") or ""
check(isinstance(ptok, str) and len(ptok) >= 16, "approved poll JSON includes a session token")
check(polled.get("username") == "admin", "approved poll JSON includes username")
setc = hdrs.get("Set-Cookie") or hdrs.get("set-cookie") or ""
check("ms_session=" in setc, "approved poll still sets the ms_session cookie")
check(("ms_session=" + ptok) in setc.replace(" ", ""), "poll JSON token matches the cookie")
st, me, _, _ = req("/api/me", headers={"Authorization": "Bearer " + ptok}, ua=TV_UA)
check(st == 200 and me.get("username") == "admin", "Bearer token from poll JSON signs the TV in")
st, again, _, _ = req("/api/pair/poll", "POST", {"token": started["poll_token"]}, ua=TV_UA)
check(st == 200 and again.get("status") in ("consumed", "unknown"),
      "a second poll after redeem is consumed/unknown (%s)" % again.get("status"))
check(not again.get("token"), "consumed poll does not return another token")

if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
