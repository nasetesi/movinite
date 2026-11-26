"""2.1.1: signed-out TV sign-in chrome, pair-code reuse, rate limit on real client IP, header color."""
import json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v211-"))
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

# --- source checks ---
js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
from app.version import __version__
print("source")
check(__version__ == "2.1.1", "version is 2.1.1")
check("## 2.1.1" in ch and ch.find("## 2.1.1") < ch.find("## 2.1 --"), "CHANGELOG has 2.1.1 above 2.1")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("tv-auth" in tvcss and "z-index: 80" in tvcss, "signed-out CSS hides chrome and raises #auth")
check("html.tv-mode.tv-auth #tv-hero" in tvcss, "hero is hidden while signed out")
check("syncAuth" in tvjs and "authOpen" in tvjs, "tv-plex tracks the auth screen")
check("PAIR.expires_at" in js and "force: true" in js, "client reuses a code until expiry / force")
check("hideAuth" in js and 'classList.add("tv-auth")' in js, "showAuth marks tv-auth")
check("background:var(--panel)" in css and ".top{" in css, "desktop .top uses side-panel color")
check("var(--glass-bg)" not in css.split(".top{")[1].split("}")[0], "desktop .top is not purple glass")
check("rgba(22, 22, 26, .96)" in tvcss, "TV tab bar matches the slide-out menu color")
# phone .top too
phone = [ln for ln in css.splitlines() if ".top{" in ln or "  .top{" in ln]
check(all("var(--panel)" in ln or "transparent" in ln for ln in phone), "phone/desktop .top rules use panel, not glass")

from app import auth, db, netutil, pair, settings, server  # noqa: E402
import uvicorn

db.migrate()
auth.create_user("admin", "TestPass14!", is_admin=True)
settings.put("trusted_proxies", "192.0.2.1")
netutil.invalidate()

class FakeReq:
    def __init__(self, peer, headers):
        self.client = type("C", (), {"host": peer})()
        self.headers = headers

print("client IP behind trusted proxy")
H = {"cf-connecting-ip": "203.0.113.9", "user-agent": "MediaServerAndroid/2.0.2 AndroidTV"}
check(netutil.client_ip_from("192.0.2.1", {"cf-connecting-ip": "203.0.113.9"}) == "203.0.113.9",
      "trusted OpenResty + CF-Connecting-IP -> real client")
check(netutil.client_ip_from("198.51.100.5", {"cf-connecting-ip": "203.0.113.9"}) == "198.51.100.5",
      "untrusted peer ignores forwarded headers")

print("pair reuse and rate limit")
pair._hits.clear()
pair._live.clear()
TV_UA = "MediaServerAndroid/2.0.2 AndroidTV testdevice"
base = "http://192.0.2.10:8099"
r1 = pair.start(FakeReq("192.0.2.1", {"user-agent": TV_UA, "cf-connecting-ip": "203.0.113.20"}), base)
r2 = pair.start(FakeReq("192.0.2.1", {"user-agent": TV_UA, "cf-connecting-ip": "203.0.113.20"}), base)
check(r1["code"] == r2["code"] and r1["poll_token"] == r2["poll_token"], "same IP+UA reuses the live code")
r3 = pair.start(FakeReq("192.0.2.1", {"user-agent": TV_UA, "cf-connecting-ip": "203.0.113.20"}), base, force=True)
check(r3["code"] != r1["code"], "force=True mints a new code")

# 10 new codes per IP then 429; another IP still works; password not involved
pair._hits.clear()
pair._live.clear()
ok = 0
last = None
for i in range(12):
    try:
        last = pair.start(FakeReq("192.0.2.1", {"user-agent": "ua-a", "cf-connecting-ip": "198.51.100.10"}), base, force=True)
        ok += 1
    except Exception as e:
        check(getattr(e, "status_code", None) == 429 or "Too many sign-in codes" in str(e),
              "11th+ new code from the same client is 429 (got %s after %d)" % (e, ok))
        break
else:
    check(False, "expected a 429 after 10 new codes")
check(ok == 10, "exactly 10 new codes are allowed per 10 minutes (got %d)" % ok)

# different client IP has its own bucket
try:
    other = pair.start(FakeReq("192.0.2.1", {"user-agent": "ua-b", "cf-connecting-ip": "198.51.100.11"}), base, force=True)
    check(bool(other.get("code")), "a different CF-Connecting-IP still gets a code")
except Exception as e:
    check(False, "other client should not be limited (%s)" % e)

print("HTTP: password sign-in still works after a 429; health is 2.1.1")
PORT = 18211
BASE = "http://127.0.0.1:%d" % PORT
threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                 daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=0.3).read()
        break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit("test server did not start")

def req(path, method="GET", data=None, cookies=None, ua=None, headers=None):
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
            return resp.status, jsout, cj
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            jsout = json.loads(raw.decode())
        except Exception:
            jsout = raw.decode()
        return e.code, jsout, cj

st, health, _ = req("/api/health")
check(st == 200 and health.get("version") == "2.1.1", "health is 2.1.1 (%s)" % health)
st, page, _ = req("/")
check(st == 200 and "tv-plex.js?v=2.1.1" in page and "tv-plex.css?v=2.1.1" in page, "index stamps 2.1.1 assets")

# drive the in-process limiter to 429, then login
pair._hits.clear(); pair._live.clear()
for i in range(10):
    pair.start(FakeReq("127.0.0.1", {"user-agent": "httptest"}), BASE, force=True)
try:
    pair.start(FakeReq("127.0.0.1", {"user-agent": "httptest"}), BASE, force=True)
    http_429 = False
except Exception as e:
    http_429 = getattr(e, "status_code", None) == 429
check(http_429, "loopback force-start is limited after 10")
st, body, cj = req("/api/login", "POST", {"username": "admin", "password": "TestPass14!"})
check(st == 200 and body.get("ok"), "password sign-in works after the pair-code 429 (%s)" % (body if st != 200 else "ok"))

if failed:
    raise SystemExit("%d checks failed" % failed)
print("all checks passed")
