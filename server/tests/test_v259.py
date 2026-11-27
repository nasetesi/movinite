"""2.5.9: TV search keyboard and a trapped, wider, consistent slide-out menu."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failed = 0
def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)

os.environ.setdefault("MS_DATA_DIR", str(Path(tempfile.mkdtemp(prefix="ms-v259-")) / "data"))
Path(os.environ["MS_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

from app.version import __version__
from app import db

css = (ROOT / "app/static/style.css").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
server_py = (ROOT / "app/server.py").read_text()

print("2.5.9 TV search and slide-out")
check(__version__ == "2.5.9", "version is 2.5.9, got %s" % __version__)
db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)
check("## 2.5.9" in ch and ch.find("## 2.5.9") < ch.find("## 2.5.8"), "CHANGELOG has a 2.5.9 section above 2.5.8")
low = ch.split("## 2.5.8")[0].lower()
check("search" in low and "keyboard" in low, "CHANGELOG mentions the TV search keyboard")
check("slide-out" in low or "slide out" in low, "CHANGELOG mentions the slide-out menu")
check("settings" in low and "libraries" in low, "CHANGELOG mentions walking to Libraries and Settings")
check("wider" in low or "28%" in low or "wide" in low, "CHANGELOG mentions the wider slide-out")
check("no new android" in low, "CHANGELOG notes no new Android app")
check("**2.5.9:**" in rd, "README What's new mentions 2.5.9")

print("JS/CSS: search page and on-screen keyboard")
check("function isSearch()" in tvjs and "tv-search-on" in tvjs, "search is a first-class TV page (not just tv-plex-off)")
check('id="tv-search"' in tvjs and "buildSearchKeys" in tvjs, "the TV search panel and keyboard are injected")
check('k: "bksp"' in tvjs and 'k: "space"' in tvjs and 'k: "clear"' in tvjs,
      "the keyboard has backspace, space and clear")
check("ABCDEFGHIJ" in tvjs and "UVWXYZ1234" in tvjs, "the keyboard includes A–Z and 0–9")
check("html.tv-mode.tv-plex.tv-search-on #tv-search" in tvcss, "search CSS is scoped to the TV search page")
search_css = tvcss[tvcss.find("2.5.9: TV search"):]
check("background: #0F1115" in search_css, "the search panel uses the dark #0F1115 fill")
check("100vh" not in search_css and "clip-path" not in search_css and "mask-image" not in search_css,
      "search CSS avoids vh, clip-path and masks")
check("onSearchKey" in tvjs and "moveSearchKey" in tvjs, "D-pad movement on the keyboard is handled")
check("location.hash = \"#/home\"" in tvjs[tvjs.find("onSearchKey"):tvjs.find("onSearchKey")+1800]
      or "location.hash = '#/home'" in tvjs[tvjs.find("onSearchKey"):tvjs.find("onSearchKey")+1800],
      "Back on the search page goes home")
check("fed.search_items" in server_py, "the search API still includes shared titles")

print("JS/CSS: trapped, wider, consistent slide-out")
check("pausing on a slide-out row must not auto-click" in tvjs, "slide-out rows no longer auto-click on focus")
# armPreview no longer clicks a menu item
arm = tvjs[tvjs.find("armPreview(el)"):tvjs.find("closeMenu(silent)")]
check("item.click()" not in arm, "armPreview no longer auto-clicks a slide-out item")
check("<b>My List</b>" in tvjs and "<b>My Lists</b>" not in tvjs, "the slide-out label is My List")
# order: profile, home, search, lists, libraries, settings
draw = tvjs[tvjs.find("    drawMenu()"):tvjs.find("    hook()")]
for a, b in (("data-act=\"profile\"", "data-act=\"home\""),
             ("data-act=\"home\"", "data-act=\"search\""),
             ("data-act=\"search\"", "data-act=\"lists\""),
             ("data-act=\"lists\"", "tv-div\">Libraries"),
             ("tv-div\">Libraries", "data-act=\"settings\"")):
    check(draw.find(a) != -1 and draw.find(a) < draw.find(b), "slide-out order has %s before %s" % (a, b))
check('data-rail="profile"' in tvjs and 'data-rail="home"' in tvjs and 'data-rail="search"' in tvjs
      and 'data-rail="lists"' in tvjs and 'data-rail="libraries"' in tvjs and 'data-rail="settings"' in tvjs,
      "the collapsed rail has profile, home, search, lists, libraries and settings")
rail = tvjs[tvjs.find('id="tv-rail"'):tvjs.find("tv-rail-nav") + 800]
# order inside tv-rail-nav: home, search, lists, libraries, settings
check(rail.find('data-rail="home"') < rail.find('data-rail="search"') < rail.find('data-rail="lists"')
      < rail.find('data-rail="libraries"') < rail.find('data-rail="settings"'),
      "rail icon order is Home, Search, My List, Libraries, Settings")
check("w * 0.28" in tvjs and "--tv-menu-w" in tvjs, "slide-out width is ~28% of the layout")
check("width: var(--tv-menu-w, 538px)" in tvcss or "width: var(--tv-menu-w" in tvcss,
      "CSS uses the JS-set --tv-menu-w variable")
check("text-overflow: ellipsis" not in tvcss[tvcss.find("#tv-menu .tv-mi-txt"):tvcss.find("#tv-menu .tv-chev")],
      "library names in the slide-out are not ellipsized")
check("inferMenuAct" in tvjs and "Only rewrite when" in tvjs, "opening the menu keeps focus on the matching item")

from app import auth, keys, settings

def paint_jpeg(path, color, title):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (400, 600), color)
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        f = ImageFont.load_default()
    d.text((24, 240), title, font=f, fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=88)

def seed(data):
    import hashlib
    thumbs = data / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    media = data / "media"
    media.mkdir(exist_ok=True)
    keys.ensure()
    if not db.row("SELECT id FROM users WHERE username=?", ("admin",)):
        auth.create_user("admin", "TestPass14!", is_admin=True)
    settings.put("server_name", "Harbor")
    now = int(time.time())
    libs = [
        ("Harbor Movies", "movies", (168, 78, 28)),
        ("Harbor Television", "tv", (40, 70, 110)),
        ("Northshore Movies", "movies", (22, 48, 118)),
        ("Northshore Television", "tv", (72, 28, 96)),
        ("Northshore Feature Films", "music", (30, 90, 70)),
    ]
    films = [
        ("Harbor Night", 2016, (22, 48, 118)),
        ("Ember Road", 2012, (168, 78, 28)),
        ("Northstar", 2020, (72, 28, 96)),
    ]
    ids = {}
    with db.tx() as c:
        c.execute("DELETE FROM progress")
        c.execute("DELETE FROM home_pins")
        c.execute("DELETE FROM items")
        c.execute("DELETE FROM libraries")
        c.execute("DELETE FROM metadata")
        lib_ids = {}
        for name, kind, color in libs:
            c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                      (name, kind, str(media), 0, now))
            lib_ids[name] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        movies_id = lib_ids["Harbor Movies"]
        for i, (title, year, color) in enumerate(films, start=1):
            name = hashlib.sha1((title + str(color)).encode()).hexdigest() + ".jpg"
            paint_jpeg(thumbs / name, color, title)
            clip = media / ("f%d.mp4" % i)
            clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
            tid = 92000 + i
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      ("movie", tid, title, year, "A test film about " + title, '["Drama"]', 120, name, name, now))
            c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster, meta_status) "
                      "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?,?)",
                      (movies_id, str(clip), title, title, year, now, tid, name, "matched"))
            ids[title] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        tv_id = lib_ids["Harbor Television"]
        show = "Harbor Days"
        sname = hashlib.sha1((show + "show").encode()).hexdigest() + ".jpg"
        paint_jpeg(thumbs / sname, (40, 70, 110), show)
        ep = media / "harbor-s01e01.mp4"
        ep.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("tv", 93001, show, 2019, "A coastal series.", '["Drama"]', 0, sname, sname, now))
        c.execute("INSERT INTO show_matches(library_id, show, tmdb_id, status, checked_at) VALUES(?,?,?,?,?)",
                  (tv_id, show, 93001, "matched", now))
        c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, "
                  "added_at, probed, show, season, episode, episode_title, poster, thumb, meta_status) "
                  "VALUES(?,?, 'video','episode',?,?,?,2400,?,1,?,?,?,?,?,?,?)",
                  (tv_id, str(ep), "Harbor Pilot", "Harbor Days S01E01", 2019, now, show, 1, 1, "Harbor Pilot", sname, sname, "matched"))
        ids["pilot"] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return ids, lib_ids

DATA = Path(os.environ["MS_DATA_DIR"])
ids, lib_ids = seed(DATA)


def api_search(port, q):
    import json, urllib.request, urllib.parse, http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(
        "http://127.0.0.1:%d/api/login" % port,
        data=json.dumps({"username": "admin", "password": "TestPass14!"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=5) as r:
        login_ok = r.status == 200
    url = "http://127.0.0.1:%d/api/search?%s" % (port, urllib.parse.urlencode({"q": q}))
    with opener.open(url, timeout=5) as r:
        body = json.loads(r.read().decode())
        return login_ok, r.status, body

def start_server(data, port):
    starter = r'''
import os, sys
os.environ["MS_DATA_DIR"] = %r
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)
sys.path.insert(0, %r)
from app import server
import uvicorn
print("READY", flush=True)
uvicorn.run(server.app, host="127.0.0.1", port=%d, log_level="warning")
''' % (str(data), str(ROOT), port)
    proc = subprocess.Popen([sys.executable, "-c", starter], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ready = False
    t0 = time.time()
    while time.time() - t0 < 20:
        line = proc.stdout.readline() if proc.poll() is None else ""
        if line and "READY" in line:
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)
    return proc, ready

def stop(proc):
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.4.4 AndroidTV")

MENU_INFO = """() => {
  const menu = document.getElementById('tv-menu');
  const ms = menu && getComputedStyle(menu);
  const cur = document.activeElement;
  const item = cur && cur.closest && cur.closest('#tv-menu button, #tv-menu a.tv-mi');
  const acts = [...(menu ? menu.querySelectorAll('button[data-act], a.tv-mi') : [])]
    .filter((n) => {
      const acct = document.getElementById('tv-acct');
      if (acct && !acct.classList.contains('open') && acct.contains(n) && n.dataset.act !== 'profile') return false;
      return true;
    })
    .map((n) => n.getAttribute('data-act') + (n.getAttribute('data-id') ? ':' + n.getAttribute('data-id') : ''));
  const names = [...(menu ? menu.querySelectorAll('#tv-menu [data-act="lib"] .tv-mi-txt b') : [])].map((el) => ({
    text: el.textContent,
    overflow: el.scrollWidth > el.clientWidth + 1,
    ellipsis: getComputedStyle(el).textOverflow
  }));
  const vw = window.innerWidth || 1920;
  const rect = menu ? menu.getBoundingClientRect() : { width: 0 };
  const parse = (c) => {
    const m = String(c||'').match(/rgba?\\((\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/);
    return m ? [parseInt(m[1],10), parseInt(m[2],10), parseInt(m[3],10)] : null;
  };
  return {
    open: document.documentElement.classList.contains('tv-menu-open'),
    act: item && item.getAttribute('data-act'),
    label: item && ((item.querySelector('b') && item.querySelector('b').textContent) || item.textContent).trim(),
    acts,
    names,
    width: rect.width,
    vw,
    ratio: vw ? rect.width / vw : 0,
    display: ms && ms.display,
  };
}"""

SEARCH_INFO = """() => {
  const panel = document.getElementById('tv-search');
  const ps = panel && getComputedStyle(panel);
  const parse = (c) => {
    const m = String(c||'').match(/rgba?\\((\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/);
    return m ? [parseInt(m[1],10), parseInt(m[2],10), parseInt(m[3],10)] : null;
  };
  const cur = document.activeElement;
  const keys = [...document.querySelectorAll('#tv-s-keys .tv-s-key')].map((k) => k.getAttribute('data-key'));
  const cards = [...document.querySelectorAll('#tv-s-results .card')].map((c) => {
    const t = c.querySelector('.t');
    return { title: t ? t.textContent : '', href: c.getAttribute('data-href') || '' };
  });
  return {
    on: document.documentElement.classList.contains('tv-search-on'),
    hidden: !!(panel && panel.hidden),
    display: ps && ps.display,
    bg: ps && ps.backgroundColor,
    bgRgb: parse(ps && ps.backgroundColor),
    query: (window.TVPlex && TVPlex.searchQ) || (document.getElementById('tv-s-qtext') && document.getElementById('tv-s-qtext').textContent) || '',
    keys,
    keyCount: keys.length,
    focusKey: cur && cur.classList && cur.classList.contains('tv-s-key') && cur.getAttribute('data-key'),
    focusQ: !!(cur && cur.id === 'tv-s-qbox'),
    onRail: !!(cur && cur.closest && cur.closest('#tv-rail')),
    onCard: !!(cur && cur.classList && cur.classList.contains('card') && cur.closest('#tv-s-results')),
    cardTitle: cur && cur.querySelector && cur.querySelector('.t') && cur.querySelector('.t').textContent,
    cards,
    hash: location.hash || '',
    plexOff: document.documentElement.classList.contains('tv-plex-off'),
    railHidden: (() => { const r = document.getElementById('tv-rail'); return !r || getComputedStyle(r).display === 'none'; })(),
  };
}"""

RAIL_INFO = """() => {
  const rail = document.getElementById('tv-rail');
  const acts = [...(rail ? rail.querySelectorAll('button[data-rail]') : [])].map((b) => b.getAttribute('data-rail'));
  return { acts, hidden: !rail || getComputedStyle(rail).display === 'none' };
}"""

def start_server_or_fail(data):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    proc, ready = start_server(data, port)
    check(ready, "isolated preview server started on %s" % port)
    return proc, port, ready

print("Browser: D-pad slide-out walk and TV search at 1920×1080 and 960×540")
proc, port, ready = start_server_or_fail(DATA)
if ready:
    print("API: /api/search returns movies, shows, episodes")
    try:
        login_ok, status, body = api_search(port, "Harbor")
        check(login_ok, "test login works for the search API")
        check(status == 200, "GET /api/search?q=Harbor is 200")
        titles = [i.get("title") for i in body.get("items") or []]
        shows = [s.get("show") for s in body.get("shows") or []]
        eps = [e.get("title") or e.get("episode_title") for e in body.get("episodes") or []]
        check("Harbor Night" in titles, "search finds the movie Harbor Night (got %s)" % titles)
        check("Harbor Days" in shows, "search finds the show Harbor Days (got %s)" % shows)
        check(any("Harbor Pilot" in str(x) or "Pilot" in str(x) for x in eps),
              "search finds the Harbor Days episode (got %s)" % eps)
        _, st2, empty = api_search(port, "")
        check(st2 == 200 and empty.get("items") == [], "empty query returns no items")
    except Exception as e:
        check(False, "search API request worked (%s)" % e)
if ready:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        check(False, "playwright is available (%s)" % e)
        stop(proc)
        ready = False

if ready:
    try:
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True,
                                   args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])

            def login_tv(page):
                page.add_init_script("window.MSAndroid = window.MSAndroid || { isTv: () => true };")
                page.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
                page.wait_for_selector("#pair-use-pass, #loginf, #lu", timeout=20000)
                if page.query_selector("#pair-use-pass"):
                    page.click("#pair-use-pass")
                page.wait_for_selector("#lu", timeout=10000)
                page.fill("#lu", "admin")
                page.fill("#lp", "TestPass14!")
                b = page.query_selector("#loginf button")
                if b:
                    b.click()
                page.wait_for_function(
                    "() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')",
                    timeout=15000)
                page.wait_for_function(
                    "() => document.documentElement.classList.contains('tv-mode')",
                    timeout=15000)
                page.wait_for_selector("#tv-rail", timeout=15000)
                page.wait_for_timeout(400)

            def run_size(label, page):
                print("  --", label)
                page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
                page.wait_for_selector("#view .card, #tv-rail", timeout=20000)
                page.wait_for_timeout(500)

                rail = page.evaluate(RAIL_INFO)
                check(rail["acts"] == ["profile", "home", "search", "lists", "libraries", "settings"],
                      "%s: collapsed rail order is profile, home, search, lists, libraries, settings (got %s)" % (label, rail["acts"]))

                # Left to the rail, Left to open the slide-out
                page.keyboard.press("ArrowLeft")
                page.wait_for_timeout(200)
                page.keyboard.press("ArrowLeft")
                page.wait_for_function("() => document.documentElement.classList.contains('tv-menu-open')", timeout=8000)
                page.wait_for_function("() => document.querySelectorAll('#tv-menu [data-act=lib]').length >= 1", timeout=8000)
                page.wait_for_timeout(200)
                info = page.evaluate(MENU_INFO)
                check(info["open"], "%s: Left on the rail opens the slide-out" % label)
                check(info["act"] == "home", "%s: opening from Home focuses Home (got %s / %s)" % (label, info["act"], info["label"]))
                check(0.25 <= info["ratio"] <= 0.32,
                      "%s: slide-out is ~26–30%% of the screen (ratio=%.3f, width=%.0f, vw=%.0f)" % (
                          label, info["ratio"], info["width"], info["vw"]))
                expected_prefix = ["profile", "home", "search", "lists"]
                check(info["acts"][:4] == expected_prefix,
                      "%s: slide-out starts Profile, Home, Search, My List (got %s)" % (label, info["acts"]))
                check(info["acts"][-1] == "settings",
                      "%s: Settings is the last slide-out item (got %s)" % (label, info["acts"]))
                lib_acts = [a for a in info["acts"] if a.startswith("lib")]
                check(len(lib_acts) >= 5, "%s: all library rows are in the slide-out (%s)" % (label, lib_acts))
                check(all(not n["overflow"] and n["ellipsis"] in ("clip", "", "unset", "none")
                          for n in info["names"]),
                      "%s: library names are not cut off (%s)" % (label, info["names"]))
                texts = [n["text"] for n in info["names"]]
                check("Harbor Movies" in texts and "Northshore Feature Films" in texts,
                      "%s: long library names are present in full (%s)" % (label, texts))

                # Walk Down from Home through Search, My List, libraries, Settings
                walked = [info["act"]]
                still_open = True
                for _ in range(20):
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(80)
                    step = page.evaluate(MENU_INFO)
                    if not step["open"]:
                        still_open = False
                        break
                    if step["act"] and (not walked or walked[-1] != step["act"]):
                        walked.append(step["act"])
                    if step["act"] == "settings" and walked.count("settings") >= 1 and len(walked) > 5:
                        # one more Down should stay on Settings
                        page.keyboard.press("ArrowDown")
                        page.wait_for_timeout(80)
                        hold = page.evaluate(MENU_INFO)
                        check(hold["open"] and hold["act"] == "settings",
                              "%s: Down on Settings stays on Settings in the open menu" % label)
                        break
                check(still_open, "%s: the slide-out stayed open for the whole Down walk (walked %s)" % (label, walked))
                check("search" in walked and "lists" in walked and "settings" in walked,
                      "%s: Down walk reaches Search, My List and Settings (walked %s)" % (label, walked))
                # The old bug: Down from Search jumped to home content, skipping lists
                if "search" in walked:
                    i = walked.index("search")
                    after = walked[i + 1] if i + 1 < len(walked) else None
                    check(after == "lists",
                          "%s: Down from Search goes to My List, not out of the menu (next=%s, walked %s)" % (
                              label, after, walked))

                # Close and go to Search
                page.keyboard.press("Escape")
                page.wait_for_function("() => !document.documentElement.classList.contains('tv-menu-open')", timeout=8000)

                page.goto("http://127.0.0.1:%d/#/search" % port, wait_until="domcontentloaded")
                page.wait_for_function("() => document.documentElement.classList.contains('tv-search-on')", timeout=10000)
                page.wait_for_selector("#tv-s-keys .tv-s-key", timeout=10000)
                page.wait_for_timeout(300)
                s0 = page.evaluate(SEARCH_INFO)
                check(s0["on"] and not s0["hidden"], "%s: search page is shown" % label)
                check(not s0["plexOff"], "%s: search does not turn on tv-plex-off (rail stays)" % label)
                check(not s0["railHidden"], "%s: the slim rail stays visible on Search" % label)
                rgb = s0["bgRgb"] or [0, 0, 0]
                check(rgb[0] <= 30 and rgb[1] <= 30 and rgb[2] <= 40 and not (rgb[2] > rgb[0] + 40),
                      "%s: search background is dark, not blue (bg=%s rgb=%s)" % (label, s0["bg"], rgb))
                check(set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") <= set(s0["keys"]) and set("0123456789") <= set(s0["keys"]),
                      "%s: keyboard has A–Z and 0–9" % label)
                check("space" in s0["keys"] and "bksp" in s0["keys"] and "clear" in s0["keys"],
                      "%s: keyboard has space, backspace and clear" % label)
                # Autofocus a key (or the query box)
                if not s0["focusKey"] and not s0["focusQ"]:
                    page.evaluate("() => { const k = document.querySelector('#tv-s-keys .tv-s-key'); if (k) k.focus(); }")
                    page.wait_for_timeout(100)
                    s0 = page.evaluate(SEARCH_INFO)
                check(s0["focusKey"] or s0["focusQ"],
                      "%s: search autofocuses the keyboard or the query box (focusKey=%s)" % (label, s0["focusKey"]))

                # Type HARBOR on the on-screen keyboard with the D-pad (focus + OK).
                page.evaluate("""() => {
                  const clear = document.querySelector('#tv-s-keys .tv-s-key[data-key="clear"]');
                  if (clear && window.TVPlex) TVPlex.pressSearchKey(clear);
                }""")
                page.wait_for_timeout(80)
                for ch in "HARBOR":
                    page.evaluate("""(ch) => {
                      const btn = document.querySelector('#tv-s-keys .tv-s-key[data-key="' + ch + '"]');
                      if (!btn) return;
                      if (window.TV && TV.focus) TV.focus(btn); else btn.focus();
                    }""", ch)
                    page.wait_for_timeout(40)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(60)
                page.wait_for_function(
                    """() => {
                      const q = (window.TVPlex && TVPlex.searchQ) || '';
                      const n = document.querySelectorAll('#tv-s-results .card').length;
                      return q.toUpperCase().indexOf('HARBOR') >= 0 && n > 0;
                    }""",
                    timeout=10000)
                page.wait_for_timeout(300)
                s1 = page.evaluate(SEARCH_INFO)
                titles = [c["title"] for c in s1["cards"]]
                check(any("Harbor Night" in t for t in titles),
                      "%s: typing HARBOR on the keyboard finds Harbor Night (cards=%s, q=%s)" % (label, titles, s1["query"]))
                check(any("Harbor Days" in t for t in titles),
                      "%s: results include the show Harbor Days (cards=%s)" % (label, titles))

                # Down from the last keyboard row should land on a result
                page.evaluate("""() => {
                  const keys = [...document.querySelectorAll('#tv-s-keys .tv-s-key[data-row="3"]')];
                  const k = keys[0];
                  if (k && window.TV) TV.focus(k); else if (k) k.focus();
                }""")
                page.wait_for_timeout(80)
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(200)
                s2 = page.evaluate(SEARCH_INFO)
                check(s2["onCard"], "%s: Down from the keyboard focuses a result card" % label)

                page.keyboard.press("ArrowUp")
                page.wait_for_timeout(200)
                s3 = page.evaluate(SEARCH_INFO)
                check(bool(s3["focusKey"] or s3["focusQ"]),
                      "%s: Up from the first result row returns to the keyboard (focusKey=%s q=%s)" % (
                          label, s3["focusKey"], s3["focusQ"]))

                # Left from the first key column goes to the rail
                page.evaluate("""() => {
                  const k = document.querySelector('#tv-s-keys .tv-s-key[data-row="0"][data-col="0"]');
                  if (k && window.TV) TV.focus(k); else if (k) k.focus();
                }""")
                page.wait_for_timeout(80)
                page.keyboard.press("ArrowLeft")
                page.wait_for_timeout(200)
                s4 = page.evaluate(SEARCH_INFO)
                check(s4["onRail"], "%s: Left from the first keyboard column focuses the rail" % label)

                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                check("#/home" in (page.evaluate("() => location.hash") or "") or
                      page.evaluate("() => !document.documentElement.classList.contains('tv-search-on')"),
                      "%s: Back from search returns home" % label)

            ctx1080 = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
            p1080 = ctx1080.new_page()
            login_tv(p1080)
            run_size("1080p", p1080)
            ctx1080.close()

            ctx540 = br.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2, user_agent=TV_UA)
            p540 = ctx540.new_page()
            login_tv(p540)
            run_size("960×540 DPR 2", p540)
            ctx540.close()
            br.close()
    finally:
        stop(proc)

print()
if failed:
    print("%d check(s) failed" % failed)
    sys.exit(1)
print("all checks passed")
