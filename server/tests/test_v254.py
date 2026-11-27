"""2.5.4: phone details top bar stays transparent; TV home is a fixed hero plus a row slot."""
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

os.environ.setdefault("MS_DATA_DIR", str(Path(tempfile.mkdtemp(prefix="ms-v254-")) / "data"))
Path(os.environ["MS_DATA_DIR"]).mkdir(parents=True, exist_ok=True)
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

from app.version import __version__
from app import db

css = (ROOT / "app/static/style.css").read_text()
js = (ROOT / "app/static/app.js").read_text()
html = (ROOT / "app/static/index.html").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()

print("2.5.4 phone details bar stays transparent")
check(__version__ == "2.5.4", "version is 2.5.4, got %s" % __version__)
db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)
check("## 2.5.4" in ch and ch.find("## 2.5.4") < ch.find("## 2.5.3"), "CHANGELOG has a 2.5.4 section")
low = ch.split("## 2.5.3")[0].lower()
check("transparent" in low or "see-through" in low, "CHANGELOG says the bar stays see-through")
check("scroll" in low, "CHANGELOG mentions scrolling")
check("no new android" in low, "CHANGELOG notes no new Android app")
check("**2.5.4:**" in rd, "README What's new mentions 2.5.4")

print("CSS: phone details stay transparent, no frosted/gray switch")
check("@media (max-width:820px)" in css and "html.detail-top:not(.tv-mode) .top{" in css,
      "the transparent header is limited to phone widths and not TV")
start = css.index("html.detail-top:not(.tv-mode) .top{")
# take the 2.5.4 phone block (up to the next min-width desktop rule after it)
phone = css[css.index("/* 2.5.2 / 2.5.4:"):css.index("@media (min-width:821px)", css.index("/* 2.5.2 / 2.5.4:"))]
check("background:transparent" in phone, "the details header is transparent")
check("linear-gradient(180deg,rgba(0,0,0," in phone, "a dark top-down scrim keeps the icons readable")
check("drop-shadow(" in phone and "text-shadow:" in phone, "icons and status text have a shadow")
check("detail-top-scrolled" not in phone, "no scrolled class restyles the header")
check("--detail-tint" not in phone, "no artwork-tint fill is used on the bar")
check("backdrop-filter" not in phone and "-webkit-backdrop-filter" not in phone,
      "no frosted glass / backdrop blur on the details bar")
check("rgba(15,17,21" not in phone, "the gray glass fallback is gone")
check(".detail-bg-phone{display:none}" in css[css.index("@media (min-width:821px)"):css.index("@media (min-width:821px)")+200]
      or ".detail-bg-phone{display:none}" in css,
      "show-page phone-only blurs are still hidden on desktop")
check("html.tv-mode .top{background:var(--panel);border-bottom:1px solid var(--line)" in css,
      "the TV top bar stays a solid panel")
top_desktop = css[css.index(".top{position:absolute;left:0;right:0;top:0;z-index:25;display:flex"):]
top_desktop = top_desktop[:top_desktop.index("}")]
check("background:var(--panel)" in top_desktop, "the default (desktop/other-page) top bar is still the solid panel")
check("--panel:#171a21" in css, "the solid bar used on other phone pages is charcoal #171A21")

tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
print("CSS/JS: TV home is a fixed hero plus a translated row track")
check("position: fixed" in tvcss.split("html.tv-mode.tv-plex .shell")[1][:250],
      "the TV shell is a fixed pane that fills the window")
check("inset: 0" in tvcss.split("html.tv-mode.tv-plex .shell")[1][:250],
      "the TV shell uses inset: 0 (no 100vh)")
check("--tv-hero-share: 62%" in tvcss, "the hero occupies a fixed ~62% share of the window")
check("top: var(--tv-hero-share)" in tvcss, "the rows pane starts under that share")
check(".tv-rows-track" in tvcss and "layoutRows()" in tvjs and "translateY(" in tvjs,
      "rows move on a translated track, not by scrolling the page")
check("html.tv-mode.tv-plex #view" in tvcss and "overflow: hidden" in tvcss.split("html.tv-mode.tv-plex #view")[1].split("}")[0],
      "the home rows pane does not scroll")
check("card .why" in tvcss, "TV hides the captions under cards")
check("scale(1.13)" in tvcss, "the focused poster scales up about 13%")
check("tv-tabs-hidden" in tvcss and "translateY(-100%)" in tvcss, "top tabs slide up and hide when you leave the first row")
check("rgba(0,0,0,.82)" in tvcss, "the slide-out dims the page heavily")
check("setTimeout(run, 300)" not in tvjs and "setTimeout(run, 80)" in tvjs,
      "hero updates are immediate, with only a short key-repeat debounce")
css_code = __import__("re").sub(r"/\*.*?\*/", "", tvcss, flags=__import__("re").S)
check("100vh" not in css_code and "clip-path" not in css_code and "vh" not in css_code,
      "the TV home layout does not use vh, 100vh or clip-path")
check("html.tv-mode.tv-plex.tv-plex-off .shell" in tvcss and "position: relative" in tvcss.split("html.tv-mode.tv-plex.tv-plex-off .shell")[1][:300],
      "details/player pages reset the fixed shell")


print("JS: no scroll switch, no theme-color or tint updates")
check("function setDetailTop(" in js, "setDetailTop is defined")
check("function clearDetailTop(" in js, "clearDetailTop is defined")
check("syncDetailTopScroll" not in js, "scrolling no longer toggles a frosted state")
check("DETAIL_TOP_Y" not in js, "the 48px scroll threshold is gone")
check("extractDetailTint" not in js and "getImageData(" not in js.split("function clearDetailTop")[0][-200:]
      if False else "extractDetailTint" not in js, "artwork tint is no longer extracted for the bar")
check("bindDetailTopScroll" not in js, "there is no scroll listener for the header style")
check('meta[name="theme-color"]' not in js, "JS does not change theme-color")
# clearDetailTop may still remove leftover tint properties; setDetailTop must not set them
set_fn = js.split("function setDetailTop")[1].split("async function route")[0]
check("setProperty" not in set_fn and "theme-color" not in set_fn and "detail-top-scrolled" not in set_fn.replace('classList.remove("detail-top-scrolled")', ""),
      "setDetailTop only turns the transparent class on, and does not add a scrolled style")
check("clearDetailTop();" in js.split("function route()")[1].split("try {")[0],
      "leaving a page clears the details header")
item = js.split("async function viewItem")[1].split("async function viewPerson")[0]
check("setDetailTop(bgImg ? thumbUrl(bgImg) : null)" in item,
      "movie and shared-title details enable the header when there is artwork")
show = js.split("async function viewShow")[1].split("async function viewAlbum")[0]
check("detail-bg detail-bg-phone" in show, "show pages still get a phone-only backdrop blur")
check("setDetailTop(showBg ? thumbUrl(showBg) : null)" in show,
      "show details enable the header when there is artwork")
calls = [ln.strip() for ln in js.splitlines() if "setDetailTop(" in ln and "function setDetailTop" not in ln]
check(all(("bgImg" in c or "showBg" in c) for c in calls) and len(calls) == 2,
      "setDetailTop is only used for movie/show details artwork, not home/library pages: %s" % calls)

print("live phone details + other pages")
PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
LONG_OV = ("A long road stretches through rust-colored hills under a late sun. "
           "The crew follows a faint radio signal, stopping in empty towns and waiting for night. "
           "Friends argue about whether to turn back, then keep going anyway.")

def paint(path, bg, title):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1280, 720), bg)
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except Exception:
        f = ImageFont.load_default()
    d.multiline_text((60, 280), title, font=f, fill=(245, 236, 255))
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
    import hashlib
    films = [
        ("Ember Road", 2012, (168, 78, 28)),
        ("Harbor Night", 2016, (22, 48, 118)),
        ("Northstar", 2020, (72, 28, 96)),
        ("River Glass", 2021, (30, 90, 70)),
    ]
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
        for i, (title, year, color) in enumerate(films, start=1):
            name = hashlib.sha1((title + str(color)).encode()).hexdigest() + ".jpg"
            paint(thumbs / name, color, title)
            clip = media / ("f%d.mp4" % i)
            clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
            tid = 91000 + i
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      ("movie", tid, title, year, LONG_OV, '["Drama"]', 128, name, name, now))
            c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster, meta_status) "
                      "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?,?)",
                      (lid, str(clip), title, title, year, now, tid, name, "matched"))
            ids[title] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        uid = c.execute("SELECT id FROM users WHERE username=?", ("admin",)).fetchone()[0]
        for title, pos in (("Ember Road", 800), ("Harbor Night", 400)):
            c.execute("INSERT INTO progress(user_id, item_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                      (uid, ids[title], pos, 7200, now))
        c.execute("INSERT OR REPLACE INTO home_pins(row, item_id, mode, created_at) VALUES(?,?,?,?)",
                  ("recommended", ids["Northstar"], 1, now))
    return ids["Ember Road"], lid

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

BAR = """() => {
  const top = document.querySelector('.top');
  const cs = top ? getComputedStyle(top) : null;
  const meta = document.querySelector('meta[name="theme-color"]');
  const v = document.getElementById('view');
  return {
    detailTop: document.documentElement.classList.contains('detail-top'),
    scrolled: document.documentElement.classList.contains('detail-top-scrolled'),
    bg: cs && cs.backgroundColor,
    bgImage: cs && cs.backgroundImage,
    backdrop: cs && (cs.backdropFilter || cs.webkitBackdropFilter || ''),
    border: cs && cs.borderBottomColor,
    tint: document.documentElement.style.getPropertyValue('--detail-tint'),
    theme: meta && meta.getAttribute('content'),
    scrollTop: v && v.scrollTop,
    view: document.getElementById('view') && document.getElementById('view').dataset.view,
  };
}"""

DATA = Path(os.environ["MS_DATA_DIR"])
iid, lid = seed(DATA)
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
proc, ready = start_server(DATA, port)
check(ready, "isolated preview server started")
if ready:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True,
                                   args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
            ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                 user_agent=PHONE_UA, is_mobile=True, has_touch=True)
            page = ctx.new_page()
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

            def is_clear(bg):
                if not bg:
                    return False
                s = bg.replace(" ", "")
                return s in ("transparent", "rgba(0,0,0,0)", "rgba(0,0,0,0.0)") or s.startswith("rgba(0,0,0,0)")

            # Home: solid charcoal bar
            page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            home = page.evaluate(BAR)
            check(not home["detailTop"] and not home["scrolled"], "home does not use the details transparent header")
            check(home["bg"] and "23, 26, 33" in home["bg"].replace(" ", " "),
                  "home uses the solid charcoal bar (bg=%s)" % home["bg"] if "23, 26, 33" not in (home["bg"] or "").replace(" ", " ") else "home uses the solid charcoal bar")
            # fix the check - rgb(23, 26, 33)
            check("23, 26, 33" in (home["bg"] or "") or "23,26,33" in (home["bg"] or "").replace(" ", ""),
                  "home top bar is solid #171A21 (bg=%s)" % home["bg"])

            # Libraries tab/page if present
            page.goto("http://127.0.0.1:%d/#/library/%d" % (port, lid), wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            lib = page.evaluate(BAR)
            check(not lib["detailTop"], "library page does not use the details transparent header")
            check("23, 26, 33" in (lib["bg"] or "") or "23,26,33" in (lib["bg"] or "").replace(" ", ""),
                  "library top bar is the solid charcoal bar (bg=%s)" % lib["bg"])

            # Details at rest
            page.goto("http://127.0.0.1:%d/#/item/%d" % (port, iid), wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.documentElement.classList.contains('detail-top')",
                timeout=15000)
            page.wait_for_timeout(400)
            top = page.evaluate(BAR)
            check(top["detailTop"], "details page turns the transparent header on")
            check(not top["scrolled"], "the scrolled class is not set at the top of the page")
            check(is_clear(top["bg"]), "at the top, the bar background is transparent (bg=%s)" % top["bg"])
            check("none" in (top["backdrop"] or "none") or top["backdrop"] in ("", "none"),
                  "at the top, there is no frosted blur (backdrop=%s)" % top["backdrop"])
            check(not (top["tint"] or "").strip(), "no --detail-tint is applied")

            # Scroll mid-page
            page.evaluate("() => { const v = document.getElementById('view'); if (v) v.scrollTop = 480; }")
            page.wait_for_timeout(400)
            mid = page.evaluate(BAR)
            check(mid["scrollTop"] and mid["scrollTop"] >= 200, "the details page was scrolled mid-page (scrollTop=%s)" % mid["scrollTop"])
            check(mid["detailTop"] and not mid["scrolled"],
                  "after scrolling, detail-top is still on and detail-top-scrolled is not (scrolled=%s)" % mid["scrolled"])
            check(is_clear(mid["bg"]), "after scrolling, the bar stays transparent (bg=%s)" % mid["bg"])
            check("none" in (mid["backdrop"] or "none") or mid["backdrop"] in ("", "none"),
                  "after scrolling, there is still no frosted blur (backdrop=%s)" % mid["backdrop"])
            check(not (mid["tint"] or "").strip(), "after scrolling, no --detail-tint is applied")
            # theme-color should not have been changed to a gray/tint
            check(mid["theme"] in (None, "", "#0b0612", "#0F1115", "#0f1115") or (mid["theme"] and mid["theme"].lower() in ("#0b0612", "#0f1115")),
                  "theme-color stays the dark app color (theme=%s)" % mid["theme"])

            # TV home: 1920x1080 and a short Android-WebView-like 960x540 @ DPR 2
            TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.4.4 AndroidTV")
            TV_LAYOUT = """() => {
              const view = document.getElementById('view');
              const hero = document.getElementById('tv-hero');
              const meta = document.querySelector('#tv-hero .tv-hero-meta');
              const tabs = document.getElementById('tv-tabs');
              const top = document.getElementById('tv-top');
              const track = view && view.querySelector(':scope > .tv-rows-track');
              const rows = track ? [...track.querySelectorAll(':scope > .tv-home-row')] : [];
              const vr = view ? view.getBoundingClientRect() : null;
              const mr = meta ? meta.getBoundingClientRect() : null;
              const hr = hero ? hero.getBoundingClientRect() : null;
              const tr = top ? top.getBoundingClientRect() : null;
              const cards = [...document.querySelectorAll('#view .card')].map(c => {
                const r = c.getBoundingClientRect();
                const art = c.querySelector('.art');
                const acs = art ? getComputedStyle(art) : null;
                const why = c.querySelector('.why');
                const title = c.querySelector('.t, .s, .hov, .why');
                return {
                  top:r.top, bottom:r.bottom, left:r.left, right:r.right, h:r.height, w:r.width,
                  focused: document.activeElement === c,
                  scale: (getComputedStyle(c).transform || ''),
                  border: acs && acs.borderTopColor + ' ' + acs.borderTopWidth,
                  whyOn: !!(why && getComputedStyle(why).display !== 'none' && why.offsetHeight > 0),
                  captionOn: !!(title && getComputedStyle(title).display !== 'none' && title.offsetHeight > 0),
                };
              });
              const heads = [...document.querySelectorAll('#view .row-head')].map(h => {
                const r = h.getBoundingClientRect();
                return {t:(h.textContent||'').replace(/\\s+/g,' ').trim(), top:r.top, bottom:r.bottom, h:r.height};
              });
              const inPane = (r) => r && vr && r.bottom > vr.top + 2 && r.top < vr.bottom - 2;
              const H = window.innerHeight;
              const visCards = cards.filter(c => inPane(c) && c.h > 40 && c.w > 40);
              const visHeads = heads.filter(h => inPane(h) && h.h > 8);
              const peekHeads = heads.filter(h => h.top < H && h.top > (vr ? vr.top + (vr.height * 0.55) : H * 0.75) && h.bottom > (vr ? vr.top + 8 : 0));
              return {
                tvPlex: document.documentElement.classList.contains('tv-plex'),
                tabsHidden: document.documentElement.classList.contains('tv-tabs-hidden'),
                menuOpen: document.documentElement.classList.contains('tv-menu-open'),
                innerH: H,
                innerW: window.innerWidth,
                viewTop: vr && vr.top,
                viewBottom: vr && vr.bottom,
                viewH: vr && vr.height,
                viewScroll: view && view.scrollTop,
                heroH: hr && hr.height,
                metaBottom: mr && mr.bottom,
                tabBottom: tabs && tabs.getBoundingClientRect().bottom,
                topBottom: tr && tr.bottom,
                topTop: tr && tr.top,
                track: !!track,
                rowCount: rows.length,
                rowIndex: (window.TVPlex && window.TVPlex._rowIndex) || (document.documentElement.classList.contains('tv-tabs-hidden') ? 1 : 0),
                transform: track ? getComputedStyle(track).transform : '',
                heads: heads,
                visHeads: visHeads.map(h => h.t),
                visCards: visCards.length,
                firstCardTop: visCards.length ? visCards[0].top : null,
                focused: cards.find(c => c.focused) || null,
                anyWhy: cards.some(c => c.whyOn),
                anyCaption: cards.some(c => c.captionOn),
                dimOn: !!(document.getElementById('tv-dim') && getComputedStyle(document.getElementById('tv-dim')).display !== 'none'),
              };
            }"""

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
                page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
                page.wait_for_selector("#tv-hero, #view .card", timeout=20000)
                page.wait_for_timeout(500)
                page.evaluate("""() => {
                  const c = document.querySelector('#view .strip.cw .card, #view .strip .card, #view .card');
                  if (c && window.TV) TV.focus(c);
                }""")
                page.wait_for_timeout(300)

            def check_tv(label, info, expect_top, min_pane):
                check(info["tvPlex"], "%s: TV plex home is on" % label)
                check(info["track"], "%s: the home rows are wrapped on a track" % label)
                check(info["viewH"] is not None and info["viewH"] >= min_pane,
                      "%s: rows pane has height (h=%s, top=%s, bottom=%s, innerH=%s)" % (
                          label, info["viewH"], info["viewTop"], info["viewBottom"], info["innerH"]))
                lo, hi = expect_top
                check(info["viewTop"] is not None and lo <= info["viewTop"] <= hi,
                      "%s: rows start under the hero (top=%s, expected %s–%s)" % (label, info["viewTop"], lo, hi))
                if info.get("heroH") is not None and info.get("innerH"):
                    share = info["heroH"] / info["innerH"]
                    check(0.58 <= share <= 0.68,
                          "%s: hero is about 60–65%% of the screen (share=%.3f, h=%s)" % (label, share, info["heroH"]))
                check(info["viewBottom"] is not None and info["viewBottom"] >= info["innerH"] - 4,
                      "%s: rows pane reaches the bottom of the window (bottom=%s innerH=%s)" % (
                          label, info["viewBottom"], info["innerH"]))
                check(not info.get("viewScroll"),
                      "%s: the page itself does not scroll (scrollTop=%s)" % (label, info.get("viewScroll")))
                if info.get("metaBottom") is not None:
                    check(info["metaBottom"] <= info["viewTop"] + 24,
                          "%s: hero details sit above the rows (metaBottom=%s viewTop=%s)" % (
                              label, info["metaBottom"], info["viewTop"]))
                check(info["visCards"] >= 1,
                      "%s: at least one poster is visible in the window (visible=%s heads=%s)" % (
                          label, info["visCards"], info.get("heads")))
                check(not info.get("anyCaption") and not info.get("anyWhy"),
                      "%s: no titles or captions under the cards" % label)

            def head_named(info, part):
                return next((h for h in (info.get("heads") or []) if part.lower() in (h.get("t") or "").lower()), None)

            def check_first_row(label, info):
                check(not info["tabsHidden"], "%s first row: top tabs are visible" % label)
                cw = head_named(info, "Continue watching")
                if cw:
                    check(cw["top"] >= info["viewTop"] - 4 and cw["bottom"] <= info["innerH"] + 4,
                          "%s first row: Continue watching sits in the row slot (top=%s)" % (label, cw["top"]))
                # The next row should peek from the bottom (heading or cards crossing the bottom edge).
                later = [h for h in (info.get("heads") or []) if "continue watching" not in (h.get("t") or "").lower()]
                peek = [h for h in later if h["top"] < info["innerH"] and h["bottom"] > info["viewTop"] and h["top"] > info["viewTop"] + 40]
                check(len(peek) >= 1 or any(h["top"] < info["innerH"] and h["top"] > info["innerH"] * 0.7 for h in later),
                      "%s first row: the next row peeks at the bottom (heads=%s)" % (label, info.get("heads")))

            def check_second_row(label, first, second):
                check(second["tabsHidden"], "%s second row: top tabs are hidden" % label)
                check(second.get("viewScroll") in (0, None), "%s second row: still no page scroll" % label)
                # Previous row is completely gone, not clipped in the slot.
                cw = head_named(second, "Continue watching")
                if cw:
                    check(cw["bottom"] <= second["viewTop"] + 2 or cw["bottom"] <= 0,
                          "%s second row: the previous row is gone (cw bottom=%s viewTop=%s)" % (
                              label, cw["bottom"], second["viewTop"]))
                vis = second.get("visHeads") or []
                check(any("continue watching" not in (t or "").lower() for t in vis),
                      "%s second row: a later row is in the slot (visHeads=%s)" % (label, vis))
                # Focused row stays in the same slot as the first row did.
                ft = (first.get("focused") or {}).get("top")
                st = (second.get("focused") or {}).get("top")
                if ft is not None and st is not None:
                    check(abs(st - ft) <= 56,
                          "%s second row: the focused row stays in the same slot (firstTop=%s secondTop=%s)" % (
                              label, ft, st))
                foc = second.get("focused")
                if foc:
                    check("1.1" in (foc.get("scale") or "") or "matrix(1.13" in (foc.get("scale") or "") or "matrix(1.12" in (foc.get("scale") or ""),
                          "%s second row: focused poster is scaled up (transform=%s)" % (label, foc.get("scale")))

            # Full-size 1080p CSS viewport
            ctx1080 = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
            p1080 = ctx1080.new_page()
            login_tv(p1080)
            i1080 = p1080.evaluate(TV_LAYOUT)
            check_tv("1080p", i1080, (640, 730), 300)
            check_first_row("1080p", i1080)
            p1080.keyboard.press("ArrowDown")
            p1080.wait_for_timeout(450)
            i1080b = p1080.evaluate(TV_LAYOUT)
            check_tv("1080p row 2", i1080b, (640, 730), 300)
            check_second_row("1080p", i1080, i1080b)
            # Up from the second row returns to the first; tabs come back.
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(450)
            i1080u = p1080.evaluate(TV_LAYOUT)
            check(not i1080u["tabsHidden"], "1080p: tabs return after Up to the first row")
            # Up from the first row focuses the tabs.
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(250)
            on_tab = p1080.evaluate("() => !!(document.activeElement && document.activeElement.closest('#tv-tabs'))")
            check(on_tab, "1080p: Up from the first row focuses the tabs")
            # Left from the first poster still focuses the rail, then the slide-out.
            p1080.evaluate("""() => {
              const c = document.querySelector('#view .strip.cw .card, #view .strip .card, #view .card');
              if (c && window.TV) TV.focus(c);
            }""")
            p1080.wait_for_timeout(200)
            p1080.keyboard.press("ArrowLeft")
            p1080.wait_for_timeout(200)
            on_rail = p1080.evaluate("() => !!(document.activeElement && document.activeElement.closest('#tv-rail'))")
            check(on_rail, "1080p: Left from the first poster focuses the rail")
            p1080.keyboard.press("ArrowLeft")
            p1080.wait_for_timeout(300)
            i_menu = p1080.evaluate(TV_LAYOUT)
            check(i_menu["menuOpen"] and i_menu["dimOn"], "1080p: a second Left opens the slide-out and dims the page")
            p1080.keyboard.press("Escape")
            p1080.wait_for_timeout(200)
            # Details still scroll normally
            p1080.goto("http://127.0.0.1:%d/#/item/%d" % (port, iid), wait_until="domcontentloaded")
            p1080.wait_for_function(
                "() => document.documentElement.classList.contains('tv-plex-off') && document.querySelector('#view h1, #view .actions, .detail-bg, #view .hero-text')",
                timeout=15000)
            p1080.wait_for_timeout(300)
            det = p1080.evaluate("""() => {
              const v = document.getElementById('view');
              const cs = v && getComputedStyle(v);
              return {
                off: document.documentElement.classList.contains('tv-plex-off'),
                pos: cs && cs.position,
                overflowY: cs && cs.overflowY,
              };
            }""")
            check(det["off"] and det["pos"] in ("static", "relative") and det["overflowY"] in ("auto", "scroll", "overlay"),
                  "1080p: details pages leave the fixed home pane and can scroll (off=%s pos=%s overflow=%s)" % (
                      det["off"], det["pos"], det["overflowY"]))
            ctx1080.close()

            # Short Android TV WebView: 960x540 CSS px at DPR 2 (physical 1920x1080)
            ctx540 = br.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2, user_agent=TV_UA)
            p540 = ctx540.new_page()
            login_tv(p540)
            i540 = p540.evaluate(TV_LAYOUT)
            check_tv("540 WebView", i540, (300, 370), 160)
            check_first_row("540 WebView", i540)
            # The 2.5.3 bug: reserve 560px on a 540px viewport made the pane height ~0
            check(i540["viewTop"] < i540["innerH"] - 160,
                  "540 WebView: reserve is not taller than the window (top=%s innerH=%s)" % (
                      i540["viewTop"], i540["innerH"]))
            p540.keyboard.press("ArrowDown")
            p540.wait_for_timeout(450)
            i540b = p540.evaluate(TV_LAYOUT)
            check_tv("540 WebView row 2", i540b, (300, 370), 160)
            check_second_row("540 WebView", i540, i540b)
            ctx540.close()

            br.close()
    except Exception as e:
        check(False, "live phone layout test ran (%s)" % e)
    finally:
        stop(proc)
else:
    stop(proc)

print("failed" if failed else "all ok")
sys.exit(1 if failed else 0)
