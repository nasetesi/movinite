"""2.1.3: pair poll limit per code+IP, 3s poll with 429 backoff, password form stops polling."""
import json, os, shutil, sys, tempfile, threading, time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v213-"))
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

css = (ROOT / "app/static/style.css").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
appjs = (ROOT / "app/static/app.js").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
pair_src = (ROOT / "app/pair.py").read_text()
from app.version import __version__
from app import db, auth, pair

print("source")
check(__version__ == "2.1.3", "version is 2.1.3")
check("## 2.1.3" in ch and ch.find("## 2.1.3") < ch.find("## 2.1.2"), "CHANGELOG has 2.1.3 above 2.1.2")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")
check("POLL_LIMIT = 400" in pair_src, "poll limit is 400 per code+IP")
check("POLL_IP_LIMIT = 800" in pair_src, "coarse per-IP poll cap is 800")
check('"%s:%s" % (ip or "?", ph)' in pair_src or '"%s:%s" % (ip or "?"' in pair_src, "poll bucket is keyed with IP and token hash")
check("pollip" in pair_src, "separate per-IP poll cap exists")
# client: 3s interval, backoff, no #lerr on 429, password stops poll
tick = appjs[appjs.find("function tickPairPoll"):appjs.find("function showPairCodeEntry")]
check("Math.max(3000" in tick and ", 1500)" not in tick and "}, 1500)" not in tick, "poll interval is 3s, not 1.5s")
check("e.status === 429" in tick and "PAIR.delay" in tick, "429 backs off the poll delay")
# comments may mention #lerr; the 429 path must not assign to the error element
code_lines = [ln for ln in tick.splitlines() if not ln.strip().startswith("//")]
code = "\n".join(code_lines)
check("err.textContent" not in code and "lerr" not in code.replace("#lerr",""),
      "poll 429 does not write the error onto the form")
pw = appjs[appjs.find("function showPasswordLogin"):appjs.find("function showTvPairLogin")]
check("stopPairPoll()" in pw, "opening the password form stops the approval poll")
hide = appjs[appjs.find("function hideAuth"):appjs.find("function focusAuth")]
check("stopPairPoll()" in hide, "leaving the sign-in screen stops the poll")
check("delay: 3000" in appjs and "PAIR.delay = 3000" in appjs, "poll delay resets to 3s")

print("limiter and password sign-in")
db.migrate()
auth.create_user("admin", "TestPass14!", is_admin=True)

class FakeReq:
    def __init__(self, ip="198.51.100.10", ua="MediaServerAndroid/2.0.2 AndroidTV"):
        self.client = type("C", (), {"host": ip})()
        self.headers = {"user-agent": ua, "x-forwarded-for": "", "cf-connecting-ip": "", "x-real-ip": ""}

# two codes, same IP: exhausting one must not 429 the other immediately
r1 = pair.start(FakeReq(), base_url="http://192.0.2.10", force=True)
r2 = pair.start(FakeReq(), base_url="http://192.0.2.10", force=True)
check(r1["poll_token"] != r2["poll_token"], "force start mints two codes")
# fill first token's bucket
tripped = False
for i in range(pair.POLL_LIMIT + 5):
    try:
        pair.poll(FakeReq(), r1["poll_token"])
    except Exception as e:
        if getattr(e, "status_code", None) == 429 or "Too many checks" in str(e):
            tripped = True
            check(i >= pair.POLL_LIMIT, "first code trips at or after POLL_LIMIT (i=%d)" % i)
            break
        raise
check(tripped, "first code eventually hits the 400-check limit")
# second code on the same IP should still poll
try:
    st = pair.poll(FakeReq(), r2["poll_token"])
    check(st.get("status") == "pending", "second code on the same IP is not blocked by the first code's bucket (%s)" % st)
except Exception as e:
    check(False, "second code should not 429: %s" % e)

print("live server")
from app import server
import uvicorn
port = 18213
def run():
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
th = threading.Thread(target=run, daemon=True)
th.start()
# wait
opener_ready = False
for _ in range(40):
    try:
        build_opener().open(Request("http://127.0.0.1:%d/api/health" % port), timeout=1)
        opener_ready = True
        break
    except Exception:
        time.sleep(0.15)
check(opener_ready, "preview-like server started")

def req(path, method="GET", body=None, ua="MediaServerAndroid/2.0.2 AndroidTV", cookies=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"User-Agent": ua, "Content-Type": "application/json"}
    handlers = []
    if cookies is not None:
        handlers.append(HTTPCookieProcessor(cookies))
    op = build_opener(*handlers)
    r = Request("http://127.0.0.1:%d%s" % (port, path), data=data, headers=headers, method=method)
    try:
        with op.open(r, timeout=10) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw.decode())
            except Exception:
                parsed = raw.decode()
            return resp.status, parsed, cookies
    except HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw.decode())
        except Exception:
            parsed = raw.decode()
        return e.code, parsed, cookies

st, health, _ = req("/api/health")
check(st == 200 and health.get("version") == "2.1.3", "health reports 2.1.3")

cj = CookieJar()
st, body, _ = req("/api/login", "POST", {"username": "admin", "password": "TestPass14!"}, cookies=cj)
check(st == 200 and body.get("ok"), "live password login 200")

# start + 50 polls stay 200 (well under 400)
st, started, _ = req("/api/pair/start", "POST", {}, ua="Mozilla/5.0 BRAVIA MediaServerAndroid/2.0.2 AndroidTV")
check(st == 200 and started.get("poll_token") and started.get("code"), "pair/start 200")
token = started["poll_token"]
statuses = []
for i in range(50):
    st, polled, _ = req("/api/pair/poll", "POST", {"token": token}, ua="Mozilla/5.0 BRAVIA MediaServerAndroid/2.0.2 AndroidTV")
    statuses.append(st)
check(all(s == 200 for s in statuses) and statuses[-1] == 200, "50 polls in a burst stay under the 400 limit (last=%s)" % statuses[-1])
st, body, _ = req("/api/login", "POST", {"username": "admin", "password": "TestPass14!"})
check(st == 200 and body.get("ok"), "password login still works after a burst of pair polls")

# wrong-password 401 is a login failure, not a poll 429
st, err, _ = req("/api/login", "POST", {"username": "admin", "password": "nope-not-the-password"})
check(st == 401, "wrong password is 401, not a poll 429 (%s)" % st)

print()
if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("all tests passed")
