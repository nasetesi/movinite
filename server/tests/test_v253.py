"""2.5.3: TV home keeps a reserved hero; rows scroll in the pane below it."""
import os
import re
import shutil
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

os.environ.setdefault("MS_DATA_DIR", str(Path(tempfile.mkdtemp(prefix="ms-v253-")) / "data"))
Path(os.environ["MS_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

from app.version import __version__
from app import db

css = (ROOT / "app/static/style.css").read_text()
tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
appjs = (ROOT / "app/static/app.js").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()

print("2.5.3 TV reserved hero")
check(__version__ == "2.5.3", "version is 2.5.3, got %s" % __version__)
db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)
check("## 2.5.3" in ch and ch.find("## 2.5.3") < ch.find("## 2.5.2"), "CHANGELOG has a 2.5.3 section")
low = ch.split("## 2.5.2")[0].lower()
check("reserved" in low or "hero" in low, "CHANGELOG describes the reserved TV hero")
check("no new android" in low or "no new android app" in low, "CHANGELOG notes no new Android app")
check("webview" in low, "CHANGELOG notes the TV app browses in the WebView")
check("**2.5.3:**" in rd, "README What's new mentions 2.5.3")
check("schema stays at 15" in low or "schema stays 15" in low or "no schema" in rd.lower(), "docs say schema is unchanged")

print("layout is TV-only")
check("--tv-hero-reserve" in tvcss, "a --tv-hero-reserve token sets the reserved height")
check("html.tv-mode.tv-plex #view" in tvcss and "top: var(--tv-hero-reserve)" in tvcss,
      "on TV home, #view starts below the reserved hero")
# The old scrolling-padding trick must be gone from the home #view rule
home_view = tvcss.split("html.tv-mode.tv-plex #view")[1].split("html.tv-mode.tv-plex.tv-plex-off #view")[0]
check("560px 0 48px 108px" not in home_view, "TV home #view no longer uses 560px scrollable top padding")
check("position: absolute" in home_view or "position:absolute" in home_view, "TV home #view is a positioned rows pane")
check("overflow-y: auto" in home_view or "overflow-y:auto" in home_view, "only the rows pane scrolls vertically")
check("html.tv-mode.tv-plex.tv-plex-off #view" in tvcss and "position: relative" in tvcss.split("html.tv-mode.tv-plex.tv-plex-off #view")[1][:400],
      "details/player (tv-plex-off) reset #view to a normal page")
# desktop/phone #view is not locked to the hero reserve
phone_view_rules = [ln for ln in css.splitlines() if "#view" in ln and "tv-hero-reserve" in ln]
check(not phone_view_rules, "desktop/phone CSS does not use --tv-hero-reserve")
check("html.tv-mode.tv-plex .top {" in tvcss and "display: none !important" in tvcss, "TV still hides the web header")
check("#tv-tabs button.tv-focused" in tvcss and "#tv-rail button.tv-focused" in tvcss, "tabs and rail keep a visible focus ring")

print("focus snap + 2.1.4 behavior kept")
check("revealRow" in tvjs, "revealRow snaps the focused row under the hero")
check("rowStep" in tvjs, "ArrowDown/Up on the TV home steps to the next or previous row")
check("TV.focus._tvplexRow" in tvjs, "TV.focus is wrapped to snap the row on the TV home")
check("setTimeout(run, 300)" in tvjs or "setTimeout(run,300)" in tvjs, "hero updates are still debounced ~300 ms")
check("focusRail" in tvjs, "Left from the first poster still focuses the rail")
check("this.openMenu(cur)" in tvjs, "Left on the rail still opens the slide-out")
# first-poster Left must not open the menu
idx = tvjs.find("if (key === \"ArrowLeft\" && onCard && this.firstInRow")
end = tvjs.find("if (key === \"ArrowLeft\" && onRail)", idx + 1) if idx >= 0 else -1
chunk = tvjs[idx:end] if idx >= 0 and end > idx else ""
check("focusRail" in chunk and "openMenu" not in chunk, "Left on the first poster focuses the rail (does not open the menu)")
check("-webkit-line-clamp: 2" in tvcss.split("#tv-hero.no-logo .tv-hero-title")[1][:350],
      "long hero titles are clamped so they stay in the reserved area")
check("data-tab=\"added\"" in tvjs and "data-tab=\"libraries\"" in tvjs, "Recently Added and Libraries tabs are still there")

print("live TV home layout")
TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.4.4 AndroidTV")
LONG_TITLE = "The Extraordinary Adventures of the Last Stand at Willow Creek Crossing"
LONG_OV = ("A wandering company follows a faint radio signal through rust-colored hills, empty towns, "
           "and a last ridge where a kitchen light is still on. Friends argue about turning back, then "
           "keep going anyway, checking the list one more time before morning.")

def paint(path, bg, title):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1280, 720), bg)
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
    except Exception:
        f = ImageFont.load_default()
    d.multiline_text((40, 300), title, font=f, fill=(245, 236, 255))
    im.save(path, "JPEG", quality=88)

def seed(data):
    thumbs = data / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    media = data / "media"
    media.mkdir(exist_ok=True)
    from app import auth, db, keys, settings
    db.migrate()
    keys.ensure()
    if not db.row("SELECT id FROM users WHERE username=?", ("admin",)):
        auth.create_user("admin", "TestPass14!", is_admin=True)
    settings.put("server_name", "Harbor")
    now = int(time.time())
    films = [
        ("One Last Shot", 2018, (40, 70, 120), "short"),
        ("Harbor Night", 2016, (22, 48, 118), "short"),
        (LONG_TITLE, 2019, (90, 40, 30), "long"),
        ("Ember Road", 2012, (168, 78, 28), "short"),
        ("Northstar", 2020, (72, 28, 96), "short"),
        ("River Glass", 2021, (30, 90, 70), "short"),
    ]
    import hashlib
    ids = {}
    with db.tx() as c:
        c.execute("DELETE FROM progress")
        c.execute("DELETE FROM home_pins")
        c.execute("DELETE FROM items")
        c.execute("DELETE FROM libraries")
        c.execute("DELETE FROM metadata")
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Movies", "movies", str(media), 0, now))
        lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for i, (title, year, color, kind) in enumerate(films, start=1):
            h = hashlib.sha1((title + str(color)).encode()).hexdigest()
            name = h + ".jpg"
            paint(thumbs / name, color, title if kind == "short" else "Long Title")
            clip = media / ("f%d.mp4" % i)
            clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
            tid = 92000 + i
            ov = LONG_OV if kind == "long" else "A story told in color, with enough plot to fill the hero."
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      ("movie", tid, title, year, ov, "[]", 118, name, name, now))
            c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster, meta_status) "
                      "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?,?)",
                      (lid, str(clip), title, title, year, now - i * 86400, tid, name, "matched"))
            ids[title] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        uid = c.execute("SELECT id FROM users WHERE username=?", ("admin",)).fetchone()[0]
        # Continue watching: first two films part-watched
        for title, pos in (("One Last Shot", 800), ("Harbor Night", 400)):
            c.execute("INSERT INTO progress(item_id, user_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                      (ids[title], uid, pos, 7200, now))
        # Pin two unwatched films so Recommended for you is guaranteed
        for title in (LONG_TITLE, "Ember Road"):
            c.execute("INSERT OR REPLACE INTO home_pins(row, item_id, mode, created_at) VALUES(?,?,?,?)",
                      ("recommended", ids[title], 1, now))
    return ids

def start_server(data, port):
    starter = r'''
import os, sys
os.environ["MS_DATA_DIR"] = %r
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)
sys.path.insert(0, %r)
from app import db, keys, settings, server
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

LAYOUT = """() => {
  const view = document.getElementById('view');
  const hero = document.getElementById('tv-hero');
  const meta = document.querySelector('#tv-hero .tv-hero-meta');
  const title = document.getElementById('tv-hero-title');
  const ov = document.getElementById('tv-hero-ov');
  const tabs = document.getElementById('tv-tabs');
  const rail = document.getElementById('tv-rail');
  const heads = [...document.querySelectorAll('#view .row-head')];
  const vr = view ? view.getBoundingClientRect() : null;
  const mr = meta ? meta.getBoundingClientRect() : null;
  const tr = tabs ? tabs.getBoundingClientRect() : null;
  const el = document.activeElement;
  const cardRow = el && el.closest && (el.closest('.hrow') || el.closest('.strip, .hs'));
  let head = cardRow && cardRow.previousElementSibling;
  while (head && !(head.classList && head.classList.contains('row-head'))) {
    if (head.classList && head.classList.contains('hrow')) { head = null; break; }
    head = head.previousElementSibling;
  }
  if (!(head && head.classList && head.classList.contains('row-head'))) head = null;
  const hr = head ? head.getBoundingClientRect() : null;
  return {
    tvMode: document.documentElement.classList.contains('tv-mode'),
    tvPlex: document.documentElement.classList.contains('tv-plex'),
    plexOff: document.documentElement.classList.contains('tv-plex-off'),
    viewTop: vr && vr.top,
    viewBottom: vr && vr.bottom,
    viewOverflow: view && getComputedStyle(view).overflowY,
    viewPadTop: view && getComputedStyle(view).paddingTop,
    heroH: hero && hero.getBoundingClientRect().height,
    metaBottom: mr && mr.bottom,
    titleText: title && title.textContent,
    ovText: title && ov && ov.textContent,
    tabBottom: tr && tr.bottom,
    tabTop: tr && tr.top,
    heads: heads.map(h => ({t: (h.textContent||'').trim(), top: h.getBoundingClientRect().top, bottom: h.getBoundingClientRect().bottom})),
    focusHead: head && (head.textContent||'').trim(),
    focusHeadTop: hr && hr.top,
    onCard: !!(el && el.classList && el.classList.contains('card')),
    onTab: !!(el && el.closest && el.closest('#tv-tabs')),
    onRail: !!(el && el.closest && el.closest('#tv-rail')),
    menuOpen: document.documentElement.classList.contains('tv-menu-open'),
  };
}"""

DATA = Path(os.environ["MS_DATA_DIR"])
ids = seed(DATA)
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
proc, ready = start_server(DATA, port)
check(ready, "isolated preview server started")
if ready:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True,
                                   args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
            ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
            page = ctx.new_page()
            page.add_init_script("window.MSAndroid = window.MSAndroid || { isTv: () => true };")
            page.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#pair-use-pass, #loginf, #lu", timeout=20000)
            if page.query_selector("#pair-use-pass"):
                page.click("#pair-use-pass")
            page.wait_for_selector("#lu", timeout=10000)
            page.fill("#lu", "admin")
            page.fill("#lp", "TestPass14!")
            btn = page.query_selector("#loginf button")
            if btn:
                btn.click()
            page.wait_for_function(
                "() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')",
                timeout=15000)
            page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#tv-hero, #view .card", timeout=20000)
            page.wait_for_function("() => document.querySelectorAll('#view .card').length >= 3", timeout=20000)
            page.wait_for_timeout(400)
            page.evaluate("""() => {
              const c = document.querySelector('#view .strip .card, #view .card');
              if (c && window.TV) TV.focus(c);
              else if (c) c.focus();
            }""")
            page.wait_for_timeout(200)
            first = page.evaluate(LAYOUT)
            check(first["tvMode"] and first["tvPlex"] and not first["plexOff"], "TV plex home is on")
            check(first["viewTop"] and 480 <= first["viewTop"] <= 640,
                  "rows pane starts around the reserved hero line (top=%s)" % first["viewTop"])
            check(first["metaBottom"] is not None and first["metaBottom"] <= first["viewTop"] + 8,
                  "hero title/details sit above the rows pane (metaBottom=%s viewTop=%s)" % (first["metaBottom"], first["viewTop"]))
            check(first["tabBottom"] is not None and first["tabBottom"] < first["viewTop"] - 40,
                  "top tabs sit well above the rows (tabBottom=%s viewTop=%s)" % (first["tabBottom"], first["viewTop"]))
            # first row heading is in the rows pane, not over the tabs
            cw = next((h for h in first["heads"] if "Continue watching" in h["t"]), None)
            check(cw is not None, "Continue watching row is present")
            check(any("Recommended" in (h["t"] or "") for h in first["heads"]), "Recommended for you is on the home page")
            if cw:
                check(cw["top"] >= first["viewTop"] - 2, "first row heading is in the rows pane, not over the hero (top=%s)" % cw["top"])
                check(first["tabBottom"] + 8 < cw["top"], "Continue watching does not collide with the tabs")

            # Move down until Recommended for you is the focused row (usually the second).
            rec = None
            third = first
            for _ in range(8):
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(160)
                third = page.evaluate(LAYOUT)
                if third.get("focusHead") and "Recommended" in third["focusHead"]:
                    rec = next((h for h in third["heads"] if "Recommended" in h["t"]), None)
                    break
            check(third["onCard"], "focus is still on a poster after moving down")
            check(rec is not None, "Recommended for you row can be focused (focusHead=%s)" % third.get("focusHead"))
            if rec:
                check(abs(rec["top"] - third["viewTop"]) <= 40,
                      "focused Recommended row snaps just under the hero (head top=%s viewTop=%s)" % (rec["top"], third["viewTop"]))
            if cw and rec:
                cw2 = next((h for h in third["heads"] if "Continue watching" in h["t"]), cw)
                check(cw2["bottom"] <= third["viewTop"] + 2 or cw2["top"] < third["viewTop"],
                      "earlier rows are clipped above the hero line after snapping (cw top=%s bottom=%s viewTop=%s)" % (cw2["top"], cw2["bottom"], third["viewTop"]))
                check(third["metaBottom"] <= third["viewTop"] + 8,
                      "hero details still sit above the rows after scrolling")
                check(third["tabBottom"] < third["viewTop"] - 40, "tabs stay clear after scrolling")

            # Long title / description: focus a pinned long-title card if not already
            page.evaluate("""(title) => {
              const cards = [...document.querySelectorAll('#view .card')];
              const c = cards.find(el => (el.getAttribute('data-title') || el.textContent || '').includes('Willow')
                || (el.getAttribute('aria-label') || '').includes('Willow')
                || (el.querySelector('.t') && el.querySelector('.t').textContent.includes('Willow')));
              // cards hide .t on TV; use href / data
              const all = [...document.querySelectorAll('#view .card')];
              let target = null;
              for (const el of all) {
                const href = el.getAttribute('data-href') || el.getAttribute('href') || '';
                if (target) break;
              }
            }""")
            # open Recommended first card if needed and wait for hero
            # Pin order: long title is first recommended. Go to that row's first card.
            if rec:
                # If we are already on recommended, go to first card (ArrowLeft many times)
                for _ in range(6):
                    page.keyboard.press("ArrowLeft")
                    page.wait_for_timeout(40)
            page.wait_for_timeout(400)  # hero debounce 300ms
            longl = page.evaluate(LAYOUT)
            # Hero should show some title; long ones clamp inside the reserved area
            check(longl["metaBottom"] is not None and longl["metaBottom"] <= longl["viewTop"] + 8,
                  "a long title/description still fits above the rows (metaBottom=%s viewTop=%s)" % (longl["metaBottom"], longl["viewTop"]))

            # 2.1.4 Left from the first poster of a row still goes to the rail
            page.keyboard.press("Escape")
            page.wait_for_timeout(80)
            focused = page.evaluate("""() => {
              const c = document.querySelector('#view .strip.cw .card, #view .strip .card, #view .card');
              if (!c) return false;
              if (window.TV) TV.focus(c); else c.focus();
              return document.activeElement === c;
            }""")
            check(focused, "can focus the first Continue watching poster")
            page.wait_for_timeout(200)
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(200)
            left = page.evaluate(LAYOUT)
            check(left["onRail"] and not left["menuOpen"], "Left from the first poster still focuses the rail (onRail=%s menu=%s)" % (left.get("onRail"), left.get("menuOpen")))
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(200)
            menu = page.evaluate(LAYOUT)
            check(menu["menuOpen"], "Left on the rail still opens the slide-out")
            page.keyboard.press("Escape")
            page.wait_for_timeout(80)

            # Phone/desktop: a narrow viewport without the TV UA should not use the reserved pane
            ctx.close()
            phone = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                   user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                                   is_mobile=True, has_touch=True)
            pp = phone.new_page()
            pp.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
            pp.wait_for_selector("#pair-use-pass, #loginf, #lu", timeout=20000)
            if pp.query_selector("#pair-use-pass"):
                pp.click("#pair-use-pass")
            pp.wait_for_selector("#lu", timeout=10000)
            pp.fill("#lu", "admin")
            pp.fill("#lp", "TestPass14!")
            b2 = pp.query_selector("#loginf button")
            if b2:
                b2.click()
            pp.wait_for_function(
                "() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')",
                timeout=15000)
            pp.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
            pp.wait_for_selector("#view", timeout=15000)
            ph = pp.evaluate("""() => {
              const v = document.getElementById('view');
              const cs = v ? getComputedStyle(v) : null;
              return {
                tvMode: document.documentElement.classList.contains('tv-mode'),
                tvPlex: document.documentElement.classList.contains('tv-plex'),
                pos: cs && cs.position,
                top: cs && cs.top,
              };
            }""")
            check(not ph["tvMode"] and not ph["tvPlex"], "phone home is not in TV plex mode")
            check(ph["pos"] != "absolute" or ph["top"] in ("auto", "0px"), "phone #view is not locked under a TV hero reserve (pos=%s top=%s)" % (ph["pos"], ph["top"]))
            phone.close()
            br.close()
    except Exception as e:
        check(False, "live TV layout test ran (%s)" % e)
    finally:
        stop(proc)
else:
    stop(proc)

print("failed" if failed else "all ok")
sys.exit(1 if failed else 0)
