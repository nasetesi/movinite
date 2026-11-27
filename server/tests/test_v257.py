"""2.5.7: slimmer TV rail, first poster clear of the rail, single focus, phone-wide transparent bar."""
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

os.environ.setdefault("MS_DATA_DIR", str(Path(tempfile.mkdtemp(prefix="ms-v257-")) / "data"))
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

print("2.5.7 slimmer TV rail, first poster, single focus, phone-wide top bar")
check(__version__ == "2.5.7", "version is 2.5.7, got %s" % __version__)
db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "15", "schema stays at 15, got %s" % ver)
check("## 2.5.7" in ch and ch.find("## 2.5.7") < ch.find("## 2.5.6"), "CHANGELOG has a 2.5.7 section above 2.5.6")
low = ch.split("## 2.5.6")[0].lower()
check("rail" in low and ("narrow" in low or "slim" in low), "CHANGELOG mentions the slimmer left rail")
check("poster" in low or "cut off" in low or "cutoff" in low, "CHANGELOG mentions the first poster no longer being cut off")
check("icon" in low and ("middle" in low or "center" in low), "CHANGELOG mentions centering the menu icons")
check("profile" in low or "user icon" in low or "avatar" in low, "CHANGELOG mentions the profile icon staying at the top")
check("double" in low or "single" in low or "border" in low, "CHANGELOG mentions the single/double focus border")
check("transparent" in low or "see-through" in low, "CHANGELOG mentions the phone see-through top bar")
check("every screen" in low or "home, libraries" in low or "all" in low, "CHANGELOG says the phone bar applies on every screen")
check("no new android" in low, "CHANGELOG notes no new Android app")
check("**2.5.7:**" in rd, "README What's new mentions 2.5.7")

print("CSS: phone top bar is transparent on every phone screen, not just details")
check("@media (max-width:820px)" in css and "html:not(.tv-mode) .top{" in css,
      "the transparent header is limited to phone widths and not TV")
phone = css[css.index("/* 2.5.7:"):css.index("@media (min-width:821px)", css.index("/* 2.5.7:"))]
check("html:not(.tv-mode) .top{" in phone and "background:transparent" in phone,
      "every phone page (not just details) uses a transparent top bar")
check("linear-gradient(180deg,rgba(0,0,0," in phone, "a dark top-down scrim keeps the icons readable")
check("drop-shadow(" in phone and "text-shadow:" in phone, "icons and status text have a shadow")
check("detail-top-scrolled" not in phone, "no scrolled class restyles the header")
check("--detail-tint" not in phone, "no artwork-tint fill is used on the bar")
check("backdrop-filter" not in phone and "-webkit-backdrop-filter" not in phone,
      "no frosted glass / backdrop blur on the phone top bar")
check("rgba(15,17,21" not in phone, "the gray glass fallback is gone")
check("Home, Libraries, Search, Downloads, Settings" in phone or "every phone screen" in phone,
      "the comment lists the phone screens the bar applies to")
check(".detail-bg-phone{display:none}" in css[css.index("@media (min-width:821px)"):css.index("@media (min-width:821px)")+200]
      or ".detail-bg-phone{display:none}" in css,
      "show-page phone-only blurs are still hidden on desktop")
check("html.tv-mode .top{background:var(--panel);border-bottom:1px solid var(--line)" in css,
      "the TV top bar stays a solid panel")
top_desktop = css[css.index(".top{position:absolute;left:0;right:0;top:0;z-index:25;display:flex"):]
top_desktop = top_desktop[:top_desktop.index("}")]
check("background:var(--panel)" in top_desktop, "the default (desktop) top bar is still the solid panel")
idx = css.index(".top{position:absolute;left:0;right:0;top:0;z-index:25;gap:6px;padding:calc(8px + env(safe-area-inset-top))")
phone_top_rule = css[idx:css.index("}", idx)]
check("background:transparent" in phone_top_rule and "var(--panel)" not in phone_top_rule,
      "the phone @media .top rule is transparent, not the solid panel")

tvcss = (ROOT / "app/static/tv-plex.css").read_text()
tvjs = (ROOT / "app/static/tv-plex.js").read_text()
print("CSS: 2.5.6 first-load fill, no rail seam, stronger scrim, details cast")
check("#0F1115" in tvcss, "TV CSS uses the dark #0F1115 fill")
check("border-right: 0" in tvcss, "the TV rail turns off any right-edge border")
hero_block = tvcss.split("html.tv-mode.tv-plex #tv-hero {", 1)[1].split("#tv-hero .tv-hero-meta", 1)[0]
check("background: #0F1115" in hero_block, "the hero itself is an opaque #0F1115 before a backdrop loads")
check("inset: 0" in hero_block and "height: var(--tv-hero-share)" not in hero_block,
      "the hero underlay covers the whole window, not only the top share")
rail_block = tvcss.split("html.tv-mode.tv-plex #tv-rail {", 1)[1].split("html.tv-mode.tv-plex #tv-rail button", 1)[0]
check("background: #0F1115" in rail_block, "the rail fill is opaque #0F1115 (no transparent right edge)")
check("rgba(0,0,0,0)" not in rail_block, "the rail no longer fades to fully transparent")
g_block = tvcss.split("#tv-hero .tv-hero-g {", 1)[1].split("#tv-hero .tv-hero-meta", 1)[0]
check("rgba(15,17,21,.94)" in g_block or "rgba(15,17,21,0.94)" in g_block,
      "the home left scrim stays strong beside the title")
check("rgba(15,17,21,0)" in g_block or "rgba(15,17,21, 0)" in g_block,
      "the home left scrim still clears on the right")
ov_block = tvcss.split("html.tv-mode.tv-plex.tv-plex-off .detail .overview {", 1)[1].split("}", 1)[0]
check("-webkit-line-clamp: 4" in ov_block, "the details synopsis is clamped to 4 lines")
check("min-height: calc(var(--tv-screen-h, 1080px) * 0.78)" not in tvcss,
      "the details block no longer forces a 78% min-height gap")
check("* 0.38 * 2 / 3" in tvcss, "the details poster is about 38% of the screen tall")
check("* 0.17)" in tvcss or "* 0.17)" in tvcss.replace(" ", ""),
      "cast photos are about 17% of the screen tall")

print("CSS/JS: TV home typography, hidden tabs, and unclipped focus")
check("position: fixed" in tvcss.split("html.tv-mode.tv-plex .shell")[1][:250],
      "the TV shell is a fixed pane that fills the window")
check("inset: 0" in tvcss.split("html.tv-mode.tv-plex .shell")[1][:250],
      "the TV shell uses inset: 0 (no 100vh)")
shell_block = tvcss.split("html.tv-mode.tv-plex .shell {", 1)[1].split("}", 1)[0]
check("z-index: 2" in shell_block, "the shell sits above the full-window hero underlay")
check("background: transparent" in shell_block, "the shell is transparent so the hero backdrop shows through")
hero_z = tvcss.split("html.tv-mode.tv-plex #tv-hero {", 1)[1].split("}", 1)[0]
check("z-index: 0" in hero_z, "the hero underlay stays behind the rows (z-index 0)")
check("top: var(--tv-hero-share)" in tvcss, "the rows pane starts under the hero share")
check(".tv-rows-track" in tvcss and "layoutRows()" in tvjs and "translateY(" in tvjs,
      "rows move on a translated track, not by scrolling the page")
check("html.tv-mode.tv-plex #view" in tvcss and "overflow: hidden" in tvcss.split("html.tv-mode.tv-plex #view")[1].split("}")[0],
      "the home rows pane does not scroll")
check("tv-tabs-off" in tvcss and "tabsEnabled: false" in tvjs,
      "the For You / Recently Added / Libraries tabs are hidden behind a flag")
check("--tv-focus-pad" in tvcss and "html.tv-mode.tv-plex .hrow > .strip" in tvcss, "the row strip leaves room so a focused poster is not clipped")
check("--tv-title-size" in tvcss and "syncViewportVars" in tvjs, "the hero title size is tied to the window")
check("0.24" in tvjs, "posters are sized at about 24% of the screen")
check("0.11" in tvjs, "the hero title is about 11% of the 1080 layout")
check("-webkit-line-clamp: 2" in tvcss, "long hero and details titles can wrap two lines")
check("scale(1.13)" in tvcss, "the focused poster scales up about 13%")
check("card .why" in tvcss, "TV hides the captions under cards")
check("rgba(0,0,0,.82)" in tvcss, "the slide-out dims the page heavily")
check("--tv-safe-left" in tvcss and "0.008" in tvjs, "the rail uses a small left overscan pad, not a 4% inset")
check("setTimeout(run, 300)" not in tvjs and "setTimeout(run, 32)" in tvjs,
      "hero updates start immediately, with only a short key-repeat coalesce")
check("cards[i - 2]" in tvjs, "neighbor backdrops on both sides are preloaded")
css_code = __import__("re").sub(r"/\*.*?\*/", "", tvcss, flags=__import__("re").S)
check("100vh" not in css_code and "clip-path" not in css_code and "vh" not in css_code,
      "the TV home layout does not use vh, 100vh or clip-path")
check("html.tv-mode.tv-plex.tv-plex-off .shell" in tvcss and "position: relative" in tvcss.split("html.tv-mode.tv-plex.tv-plex-off .shell")[1][:300],
      "details/player pages reset the fixed shell")

print("CSS/JS: 2.5.7 slimmer centered rail, first-poster inset, single white focus")
check("tv-rail-nav" in tvcss and "tv-rail-nav" in tvjs, "Search/Home/Libraries sit in a .tv-rail-nav group")
check("justify-content: center" in tvcss.split("#tv-rail .tv-rail-nav")[1][:400],
      "the nav icons are vertically centered in the rail")
check('id="tv-rail-av"' in tvjs and 'tabindex="0"' in tvjs.split('id="tv-rail-av"')[1][:240],
      "the profile icon is a focusable rail button")
check("revealCardPastRail" in tvjs, "focusing a card scrolls it clear of the rail")
check("--tv-row-inset" in tvcss and "tv-row-inset" in tvjs, "rows start after the rail with a safe inset")
check("calc(var(--tv-rail-w) + 12px)" in tvcss, "the home pane pads content past the rail")
check("width: 200px" in tvcss.split("#tv-menu {")[1][:400], "the slide-out is slightly narrower (200px)")
check("0 0 0 7px" not in tvcss and "0 0 0 3px #fff" not in tvcss,
      "no double box-shadow focus ring remains in the TV CSS")
check("html.tv-mode.tv-plex *:focus" in tvcss and "outline: none !important" in tvcss,
      "purple focus outlines are disabled under tv-plex")
check("background: #fff !important" in tvcss and "box-shadow: none !important" in tvcss
      and "html.tv-mode.tv-plex #resume:focus" in tvcss and "html.tv-mode.tv-plex #play:focus" in tvcss,
      "focused details buttons use a white fill and override the purple ID-level ring")
check(".dsec .row-head .muted" in tvcss and "display: none" in tvcss.split(".dsec .row-head .muted")[1][:250],
      "the leftover Cast 'N of the top-billed' count is hidden on TV")
check("0.008" in tvjs and "btn = h <= 700 ? 40 : 44" in tvjs,
      "JS sizes the collapsed rail around 3.5–4% with slimmer icons")

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
        ("Northstar", 2020, (250, 210, 180)),
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
        # 2.5.6: give Ember Road a billed cast so the details layout can be measured
        ember_tid = 91001
        for i, (name, character) in enumerate((
            ("Alex Rivera", "Mara Quinn"),
            ("Jordan Hale", "Ben Cole"),
            ("Sam Oriel", "Lyn Park"),
            ("Riley Cho", "Edie Shore"),
            ("Casey Quinn", "Tom Vale"),
            ("Morgan Ellis", "Nia Brooks"),
        ), start=1):
            c.execute("INSERT INTO people(id, name, updated_at) VALUES(?,?,?)", (80000 + i, name, now))
            c.execute("INSERT INTO movie_cast(tmdb_id, person_id, character, ord) VALUES(?,?,?,?)",
                      (ember_tid, 80000 + i, character, i))
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Shows", "tv", str(media), 0, now))
        slid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        show = "Cedar Harbor"
        sname = hashlib.sha1((show + "show").encode()).hexdigest() + ".jpg"
        paint(thumbs / sname, (40, 70, 110), show)
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,poster,backdrop,fetched_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  ("tv", 92001, show, 2019, LONG_OV, '["Drama"]', sname, sname, now))
        c.execute("INSERT INTO show_matches(library_id, show, tmdb_id, status, checked_at) VALUES(?,?,?,?,?)",
                  (slid, show, 92001, "matched", now))
        for ep in range(1, 5):
            clip = media / ("s1e%d.mp4" % ep)
            clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
            c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, "
                      "added_at, probed, show, season, episode, poster, thumb, meta_status) "
                      "VALUES(?,?, 'video','episode',?,?,?,2400,?,1,?,?,?,?,?,?)",
                      (slid, str(clip), "The Landing" if ep == 1 else "Episode %d" % ep,
                       "Cedar Harbor S01E%02d" % ep, 2019, now, show, 1, ep, sname, sname, "matched"))
    return ids["Ember Road"], lid, slid

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
iid, lid, slid = seed(DATA)
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

            def check_phone_bar(label, info, expect_detail=False):
                check(bool(info.get("scrolled")) is False,
                      "%s: detail-top-scrolled is not set" % label)
                if expect_detail:
                    check(info["detailTop"], "%s: details page turns detail-top on" % label)
                else:
                    check(not info["detailTop"], "%s: does not require the details-only class" % label)
                check(is_clear(info["bg"]), "%s: the top bar background is transparent (bg=%s)" % (label, info["bg"]))
                check("none" in (info["backdrop"] or "none") or info["backdrop"] in ("", "none"),
                      "%s: no frosted blur (backdrop=%s)" % (label, info["backdrop"]))
                check(not (info["tint"] or "").strip(), "%s: no --detail-tint is applied" % label)
                check("23, 26, 33" not in (info["bg"] or "") and "23,26,33" not in (info["bg"] or "").replace(" ", ""),
                      "%s: the bar is not solid charcoal #171A21 (bg=%s)" % (label, info["bg"]))

            # Home: transparent bar (and still after a scroll)
            page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            home = page.evaluate(BAR)
            check_phone_bar("phone home", home, expect_detail=False)
            page.evaluate("() => { const v = document.getElementById('view'); if (v) v.scrollTop = 280; }")
            page.wait_for_timeout(250)
            home_mid = page.evaluate(BAR)
            check(home_mid["scrollTop"] and home_mid["scrollTop"] >= 80,
                  "phone home was scrolled (scrollTop=%s)" % home_mid["scrollTop"])
            check_phone_bar("phone home scrolled", home_mid, expect_detail=False)

            # Libraries
            page.goto("http://127.0.0.1:%d/#/library/%d" % (port, lid), wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            lib = page.evaluate(BAR)
            check_phone_bar("phone library", lib, expect_detail=False)

            # Search
            page.goto("http://127.0.0.1:%d/#/search" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            search = page.evaluate(BAR)
            check_phone_bar("phone search", search, expect_detail=False)

            # Settings
            page.goto("http://127.0.0.1:%d/#/settings" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#view, .top", timeout=15000)
            page.wait_for_timeout(300)
            settings = page.evaluate(BAR)
            check_phone_bar("phone settings", settings, expect_detail=False)

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
                const ar = art ? art.getBoundingClientRect() : null;
                return {
                  top:r.top, bottom:r.bottom, left:r.left, right:r.right, h:r.height, w:r.width,
                  artTop: ar && ar.top, artBottom: ar && ar.bottom, artH: ar && ar.height,
                  focused: document.activeElement === c,
                  scale: (getComputedStyle(c).transform || ''),
                  border: acs && acs.borderTopColor + ' ' + acs.borderTopWidth,
                  borderW: acs && parseFloat(acs.borderTopWidth || 0),
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
                unfocusedArtH: (function(){ const u=cards.filter(c => !c.focused && c.artH); return u.length ? u[0].artH : null; })(),

                anyWhy: cards.some(c => c.whyOn),
                anyCaption: cards.some(c => c.captionOn),
                dimOn: !!(document.getElementById('tv-dim') && getComputedStyle(document.getElementById('tv-dim')).display !== 'none'),
                tabsOff: document.documentElement.classList.contains('tv-tabs-off'),
                topDisplay: top ? getComputedStyle(top).display : null,
                titleSize: (function(){ const el=document.querySelector('#tv-hero .tv-hero-title'); return el ? parseFloat(getComputedStyle(el).fontSize) : 0; })(),
                metaTop: mr && mr.top,
                railPad: (function(){ const r=document.getElementById('tv-rail'); return r ? parseFloat(getComputedStyle(r).paddingLeft) : 0; })(),
                railBtn: (function(){ const b=document.querySelector('#tv-rail button[data-rail]:not(.tv-rail-av), #tv-rail button:not(.tv-rail-av)'); return b ? parseFloat(getComputedStyle(b).width) : 0; })(),
                railW: (function(){ const r=document.getElementById('tv-rail'); return r ? r.getBoundingClientRect().width : 0; })(),
                railRight: (function(){ const r=document.getElementById('tv-rail'); return r ? r.getBoundingClientRect().right : 0; })(),
                avTop: (function(){ const a=document.getElementById('tv-rail-av'); return a ? a.getBoundingClientRect().top : null; })(),
                avFocusable: (function(){ const a=document.getElementById('tv-rail-av'); return !!(a && !a.disabled && a.tabIndex >= 0); })(),
                navMid: (function(){ const n=document.querySelector('#tv-rail .tv-rail-nav'); if(!n) return null; const r=n.getBoundingClientRect(); return (r.top + r.bottom) / 2; })(),
                firstArtLeft: (function(){ const c=document.querySelector('#view .tv-home-row .card .art, #view .card .art'); return c ? c.getBoundingClientRect().left : null; })(),
                focusedArtLeft: (function(){ const c=document.querySelector('#view .card:focus .art, #view .card.tv-focused .art'); return c ? c.getBoundingClientRect().left : null; })(),
                stripPad: (function(){ const s=document.querySelector('#view .strip, #view .hs'); return s ? parseFloat(getComputedStyle(s).paddingTop) : 0; })(),
                shellZ: (function(){ const s=document.querySelector('.shell'); return s ? getComputedStyle(s).zIndex : null; })(),
                heroZ: hero ? getComputedStyle(hero).zIndex : null,
                posterHit: (function(){
                  const inView = (el) => {
                    if (!el || !vr) return false;
                    const r = el.getBoundingClientRect();
                    return r.bottom > vr.top + 2 && r.top < vr.bottom - 2 && r.height > 40 && r.width > 40;
                  };
                  let c = document.activeElement && document.activeElement.closest && document.activeElement.closest('#view .card');
                  if (!inView(c)) c = null;
                  if (!c) c = [...document.querySelectorAll('#view .card')].find(inView) || null;
                  if (!c) return null;
                  const r = c.getBoundingClientRect();
                  const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
                  if (!el) return 'none';
                  if (el.closest && el.closest('#view .card, #view .row-head, #view .strip, #view')) return 'view';
                  if (el.closest && el.closest('#tv-hero')) return 'hero';
                  if (el.closest && el.closest('#tv-rail')) return 'rail';
                  if (el.closest && el.closest('#tv-menu, #tv-dim')) return 'menu';
                  return (el.id || el.className || el.tagName || 'other');
                })(),
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
                if info.get("viewTop") is not None and info.get("innerH"):
                    share = info["viewTop"] / info["innerH"]
                    check(0.50 <= share <= 0.68,
                          "%s: the reserved hero slot is about 60%% of the screen (rows start at %.3f, viewTop=%s)" % (
                              label, share, info["viewTop"]))
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
                check(info.get("posterHit") == "view",
                      "%s: posters paint in front of the hero underlay (hit=%s shellZ=%s heroZ=%s)" % (
                          label, info.get("posterHit"), info.get("shellZ"), info.get("heroZ")))
                check(info.get("tabsOff") and info.get("topDisplay") == "none",
                      "%s: the For You / Recently Added / Libraries tabs are hidden (off=%s display=%s)" % (
                          label, info.get("tabsOff"), info.get("topDisplay")))
                check(info.get("titleSize") and info["titleSize"] >= 109,
                      "%s: hero title is large (font-size=%s)" % (label, info.get("titleSize")))
                if info.get("metaTop") is not None and info.get("innerH"):
                    check(info["metaTop"] >= info["innerH"] * 0.07,
                          "%s: hero text starts with comfortable top padding (metaTop=%s, %s%%)" % (
                              label, info["metaTop"], round(100 * info["metaTop"] / info["innerH"], 1)))
                unf = [c for c in (info.get("allArts") or []) if not c.get("focused") and c.get("artH")]
                # fall back to card heights in pane if allArts is empty
                arts = info.get("unfocusedArtH")
                if arts:
                    share = arts / info["innerH"]
                    check(0.20 <= share <= 0.30,
                          "%s: unfocused posters are about 22–25%% of the screen (h=%s share=%.3f)" % (
                              label, arts, share))
                cw = head_named(info, "Continue watching")
                if cw:
                    check(cw["top"] >= info["viewTop"] - 4 and cw["bottom"] <= info["innerH"] + 4,
                          "%s first row: Continue watching sits in the row slot (top=%s)" % (label, cw["top"]))
                foc = info.get("focused") or {}
                if foc.get("artTop") is not None:
                    check(foc["artTop"] >= info["viewTop"] - 1,
                          "%s: focused poster is not clipped at the top of the rows pane (artTop=%s viewTop=%s)" % (
                              label, foc["artTop"], info["viewTop"]))
                    if cw:
                        check(foc["artTop"] >= cw["bottom"] - 1,
                              "%s: focused poster does not overlap its row label (artTop=%s headBottom=%s)" % (
                                  label, foc["artTop"], cw["bottom"]))
                check(info.get("railW") and 0.028 * info["innerW"] <= info["railW"] <= 0.05 * info["innerW"] + 2,
                      "%s: the collapsed rail is about 3.5–4%% of the screen (w=%s innerW=%s share=%.3f)" % (
                          label, info.get("railW"), info.get("innerW"),
                          (info["railW"] / info["innerW"]) if info.get("railW") and info.get("innerW") else 0))
                check(info.get("railBtn") and 36 <= info["railBtn"] <= 52,
                      "%s: rail icons are slimmer but readable (btn=%s)" % (label, info.get("railBtn")))
                check(info.get("avTop") is not None and info["avTop"] < info["innerH"] * 0.16,
                      "%s: the profile icon stays at the top of the rail (avTop=%s)" % (label, info.get("avTop")))
                check(info.get("avFocusable"), "%s: the profile icon is focusable" % label)
                check(info.get("navMid") and abs(info["navMid"] - info["innerH"] / 2) <= info["innerH"] * 0.22,
                      "%s: the other nav icons are vertically centered (navMid=%s mid=%s)" % (
                          label, info.get("navMid"), (info["innerH"] / 2) if info.get("innerH") else None))
                rail_r = info.get("railRight") or 0
                if info.get("firstArtLeft") is not None:
                    check(info["firstArtLeft"] >= rail_r + 2,
                          "%s: the first poster is fully to the right of the rail (artLeft=%s railRight=%s)" % (
                              label, info["firstArtLeft"], rail_r))
                if info.get("focusedArtLeft") is not None:
                    check(info["focusedArtLeft"] >= rail_r + 2,
                          "%s: the focused poster's border is fully to the right of the rail (artLeft=%s railRight=%s)" % (
                              label, info["focusedArtLeft"], rail_r))
                later = [h for h in (info.get("heads") or []) if "continue watching" not in (h.get("t") or "").lower()]
                check(any(h["top"] < info["innerH"] and h["top"] > info["viewTop"] + 40 for h in later),
                      "%s first row: the next row peeks at the bottom (heads=%s)" % (label, info.get("heads")))

            def check_second_row(label, first, second):
                check(second.get("posterHit") == "view",
                      "%s second row: posters still paint in front of the hero (hit=%s)" % (
                          label, second.get("posterHit")))
                check(second.get("tabsOff") and second.get("topDisplay") == "none",
                      "%s second row: top tabs stay hidden" % label)
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
            check_tv("1080p", i1080, (600, 710), 300)
            check_first_row("1080p", i1080)
            FIRST_LOAD = """() => {
              const a = document.getElementById('tv-hero-a');
              const b = document.getElementById('tv-hero-b');
              const savedA = a && a.style.backgroundImage;
              const savedB = b && b.style.backgroundImage;
              if (a) a.style.backgroundImage = 'none';
              if (b) b.style.backgroundImage = 'none';
              const parse = (c) => {
                const m = String(c||'').match(/rgba?\\((\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)/);
                return m ? [parseInt(m[1],10), parseInt(m[2],10), parseInt(m[3],10)] : null;
              };
              const hero = document.getElementById('tv-hero');
              const rail = document.getElementById('tv-rail');
              const shell = document.querySelector('.shell');
              const g = document.querySelector('#tv-hero .tv-hero-g');
              const hs = hero && getComputedStyle(hero);
              const rs = rail && getComputedStyle(rail);
              const info = {
                heroBg: hs && hs.backgroundColor,
                heroRgb: parse(hs && hs.backgroundColor),
                bodyRgb: parse(getComputedStyle(document.body).backgroundColor),
                htmlRgb: parse(getComputedStyle(document.documentElement).backgroundColor),
                shellRgb: parse(shell && getComputedStyle(shell).backgroundColor),
                railRgb: parse(rs && rs.backgroundColor),
                railBorderW: rs && parseFloat(rs.borderRightWidth),
                railBorderStyle: rs && rs.borderRightStyle,
                railBoxShadow: rs && rs.boxShadow,
                heroInset: hs && (hs.top + ' ' + hs.right + ' ' + hs.bottom + ' ' + hs.left),
                heroH: hero && hero.getBoundingClientRect().height,
                innerH: window.innerHeight,
                scrim: g && getComputedStyle(g).backgroundImage,
              };
              if (a) a.style.backgroundImage = savedA || '';
              if (b) b.style.backgroundImage = savedB || '';
              return info;
            }"""

            def is_dark(rgb):
                return bool(rgb) and max(rgb) <= 40 and rgb[0] <= 30

            def check_first_load(label, info):
                check(is_dark(info.get("heroRgb")) and is_dark(info.get("bodyRgb")) and is_dark(info.get("railRgb")),
                      "%s first load: hero, body and rail are dark #0F1115, not a bright/blue flash (hero=%s body=%s rail=%s)" % (
                          label, info.get("heroRgb"), info.get("bodyRgb"), info.get("railRgb")))
                check((info.get("railBorderW") or 0) == 0 or info.get("railBorderStyle") == "none",
                      "%s first load: the rail has no right-edge border (w=%s style=%s)" % (
                          label, info.get("railBorderW"), info.get("railBorderStyle")))
                shadow = (info.get("railBoxShadow") or "none").replace(" ", "")
                check(shadow in ("none", "0px0px0px0px") or "255,255,255" not in (info.get("railBoxShadow") or ""),
                      "%s first load: the rail does not paint a white seam (box-shadow=%s)" % (
                          label, info.get("railBoxShadow")))
                check(info.get("heroH") and info["heroH"] >= info["innerH"] * 0.95,
                      "%s first load: the dark hero underlay covers the window (h=%s innerH=%s)" % (
                          label, info.get("heroH"), info.get("innerH")))

            load1080 = p1080.evaluate(FIRST_LOAD)
            check_first_load("1080p", load1080)
            p1080.keyboard.press("ArrowDown")
            p1080.wait_for_timeout(450)
            i1080b = p1080.evaluate(TV_LAYOUT)
            check_tv("1080p row 2", i1080b, (600, 710), 300)
            check_second_row("1080p", i1080, i1080b)
            # Up from the second row returns to the first; tabs stay hidden.
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(450)
            i1080u = p1080.evaluate(TV_LAYOUT)
            check(i1080u.get("tabsOff") and i1080u.get("topDisplay") == "none",
                  "1080p: tabs stay hidden after Up to the first row")
            # Up from the first row stays on the first poster (tabs are off).
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(250)
            stay = p1080.evaluate("""() => {
              const el = document.activeElement;
              return {
                onCard: !!(el && el.classList && el.classList.contains('card')),
                onTab: !!(el && el.closest && el.closest('#tv-tabs')),
              };
            }""")
            check(stay["onCard"] and not stay["onTab"],
                  "1080p: Up from the first row stays on the row (tabs are hidden)")
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
            # Up from the rail icons should reach the profile button.
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(120)
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(120)
            p1080.keyboard.press("ArrowUp")
            p1080.wait_for_timeout(120)
            on_av = p1080.evaluate("""() => {
              const a = document.getElementById('tv-rail-av');
              const el = document.activeElement;
              return !!(a && (el === a || (el && a.contains(el))));
            }""")
            check(on_av, "1080p: Up on the rail focuses the profile icon")
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
            p1080.wait_for_timeout(400)
            TV_DETAILS = """() => {
              const v = document.getElementById('view');
              const cs = v && getComputedStyle(v);
              const h1 = document.querySelector('#view .detail h1, #view h1');
              const hs = h1 && getComputedStyle(h1);
              const hr = h1 && h1.getBoundingClientRect();
              const ov = document.querySelector('#view .overview');
              const os = ov && getComputedStyle(ov);
              const btn = document.querySelector('#view .actions .btn, #play, #playnext, #resume');
              const bs = btn && getComputedStyle(btn);
              const br = btn && btn.getBoundingClientRect();
              const bg = document.querySelector('.detail-bg, .detail-bg-phone');
              const img = bg && bg.querySelector('.dbg-img');
              const poster = document.querySelector('#view .detail .poster');
              const pr = poster && poster.getBoundingClientRect();
              const detail = document.querySelector('#view .detail');
              const dr = detail && detail.getBoundingClientRect();
              const H = window.innerHeight;
              const people = Array.from(document.querySelectorAll('#view .cast-strip .person'));
              const castBoxes = people.map((p) => {
                const ph = p.querySelector('.pph');
                const pn = p.querySelector('.pn');
                const pr = ph && ph.getBoundingClientRect();
                const nr = pn && pn.getBoundingClientRect();
                return {
                  photoTop: pr && pr.top,
                  photoBottom: pr && pr.bottom,
                  photoH: pr && pr.height,
                  name: pn && (pn.textContent || '').trim(),
                  nameBottom: nr && nr.bottom,
                };
              });
              return {
                off: document.documentElement.classList.contains('tv-plex-off'),
                pos: cs && cs.position,
                overflowY: cs && cs.overflowY,
                title: h1 && (h1.textContent||'').trim(),
                titleSize: hs && parseFloat(hs.fontSize),
                titleClamp: hs && String(hs.webkitLineClamp || ''),
                titleTop: hr && hr.top,
                titleH: hr && hr.height,
                ovSize: os && parseFloat(os.fontSize),
                btnMinH: bs && parseFloat(bs.minHeight),
                btnSize: bs && parseFloat(bs.fontSize),
                btnTop: br && br.top,
                btnBottom: br && br.bottom,
                btnLeft: br && br.left,
                bgOn: !!bg,
                bgH: bg && bg.getBoundingClientRect().height,
                bgFilter: img && getComputedStyle(img).filter,
                posterH: pr && pr.height,
                posterTop: pr && pr.top,
                detailH: dr && dr.height,
                detailBottom: dr && dr.bottom,
                innerH: H,
                canScroll: !!(v && v.scrollHeight > v.clientHeight + 20),
                scrollTop: v && v.scrollTop,
                viewOverflow: cs && cs.overflowY,
                ovClamp: os && String(os.webkitLineClamp || ''),
                posterShare: pr && (pr.height / H),
                castCount: people.length,
                castPhotoShare: castBoxes[0] && (castBoxes[0].photoH / H),
                castPhotoBottom: castBoxes[0] && castBoxes[0].photoBottom,
                castNameBottom: castBoxes[0] && castBoxes[0].nameBottom,
                castVisible: !!(castBoxes.length && castBoxes.every((b) =>
                  b.photoTop >= -2 && b.photoBottom <= H + 4 &&
                  (!b.nameBottom || (b.nameBottom <= H + 4)))),
              };
            }"""

            def check_tv_details(label, info, scrollable=False, expect_cast=False):
                check(info["off"] and info["pos"] in ("static", "relative", "absolute") and info["overflowY"] in ("auto", "scroll", "overlay"),
                      "%s: details leave the fixed home pane and can scroll (off=%s pos=%s overflow=%s)" % (
                          label, info["off"], info["pos"], info["overflowY"]))
                check(info.get("titleSize") and info["titleSize"] >= 109,
                      "%s: details title is large (font-size=%s)" % (label, info.get("titleSize")))
                check(info.get("titleClamp") in ("2", "2.0"),
                      "%s: details title can wrap two lines (clamp=%s)" % (label, info.get("titleClamp")))
                check(info.get("titleTop") is not None and info["titleTop"] >= info["innerH"] * 0.05,
                      "%s: details title is not crammed into a corner (top=%s)" % (label, info.get("titleTop")))
                if info.get("ovSize"):
                    check(info["ovSize"] >= 22,
                          "%s: details synopsis is readable (font-size=%s)" % (label, info.get("ovSize")))
                check(info.get("btnMinH") and info["btnMinH"] >= 60 and info.get("btnSize") and info["btnSize"] >= 20,
                      "%s: details buttons are large (minH=%s font=%s)" % (label, info.get("btnMinH"), info.get("btnSize")))
                if info.get("btnBottom") is not None:
                    check(info["btnTop"] >= 0 and info["btnBottom"] <= info["innerH"] + 8,
                          "%s: focused-row buttons are on screen (top=%s bottom=%s)" % (
                              label, info.get("btnTop"), info.get("btnBottom")))
                check(info.get("bgOn") and info.get("bgH") and info["bgH"] >= info["innerH"] * 0.85,
                      "%s: backdrop is full-bleed (on=%s h=%s innerH=%s)" % (
                          label, info.get("bgOn"), info.get("bgH"), info.get("innerH")))
                filt = (info.get("bgFilter") or "none").lower()
                check("blur" not in filt,
                      "%s: backdrop is sharp, not a small blurred fill (filter=%s)" % (label, info.get("bgFilter")))
                if info.get("posterH"):
                    share = info["posterH"] / info["innerH"]
                    check(0.32 <= share <= 0.45,
                          "%s: poster is about 35-40%% of the screen (h=%s share=%.3f)" % (
                              label, info.get("posterH"), share))
                    check(info.get("posterTop") is not None and info["posterTop"] < info["innerH"] * 0.5,
                          "%s: the poster sits in the first screen next to the title (top=%s)" % (
                              label, info.get("posterTop")))
                if info.get("ovClamp"):
                    check(info["ovClamp"] in ("4", "4.0", "3", "3.0"),
                          "%s: synopsis is clamped to 3-4 lines (clamp=%s)" % (label, info.get("ovClamp")))
                if expect_cast:
                    check(info.get("castCount") and info["castCount"] >= 4,
                          "%s: billed cast is on the page (n=%s)" % (label, info.get("castCount")))
                    check(info.get("castPhotoShare") and 0.14 <= info["castPhotoShare"] <= 0.22,
                          "%s: cast photos are about 16-18%% of the screen (share=%.3f)" % (
                              label, info.get("castPhotoShare") or 0))
                    check(info.get("castVisible"),
                          "%s: the whole cast row (photos and names) fits on the first screen without scrolling (photoBottom=%s nameBottom=%s innerH=%s scrollTop=%s)" % (
                              label, info.get("castPhotoBottom"), info.get("castNameBottom"),
                              info.get("innerH"), info.get("scrollTop")))
                if scrollable:
                    check(info.get("canScroll"),
                          "%s: lower sections can scroll (scrollHeight > view)" % label)


            det = p1080.evaluate(TV_DETAILS)
            check_tv_details("1080p movie details", det, scrollable=False, expect_cast=True)
            # Focus the primary action and confirm it is fully on screen
            p1080.evaluate("""() => {
              const b = document.querySelector('#view .actions .btn, #play, #resume');
              if (b && window.TV) TV.focus(b); else if (b) b.focus();
            }""")
            p1080.wait_for_timeout(200)
            foc = p1080.evaluate("""() => {
              const b = document.activeElement;
              const r = b && b.getBoundingClientRect();
              const cs = b && getComputedStyle(b);
              const muted = document.querySelector('.dsec .row-head .muted, .detail .row-head .muted');
              const mutedCs = muted && getComputedStyle(muted);
              return {
                isBtn: !!(b && b.classList && b.classList.contains('btn')),
                border: cs && (cs.borderTopWidth + ' ' + cs.borderTopColor),
                borderW: cs && parseFloat(cs.borderTopWidth),
                boxShadow: cs && cs.boxShadow,
                outline: cs && cs.outlineStyle,
                bg: cs && cs.backgroundColor,
                color: cs && cs.color,
                top: r && r.top, bottom: r && r.bottom, left: r && r.left, right: r && r.right,
                innerH: window.innerHeight, innerW: window.innerWidth,
                mutedDisplay: mutedCs ? mutedCs.display : "missing",
                mutedText: muted ? (muted.textContent || "") : "",
              };
            }""")
            check(foc["isBtn"] and foc["top"] >= 0 and foc["bottom"] <= foc["innerH"] + 4 and foc["left"] >= 0,
                  "1080p movie details: Play is focused and fully on screen (top=%s bottom=%s border=%s)" % (
                      foc.get("top"), foc.get("bottom"), foc.get("border")))
            shadow = (foc.get("boxShadow") or "none").replace(" ", "")
            check(shadow in ("none", "0px0px0px0px") or shadow.startswith("none"),
                  "1080p movie details: focused button has no extra box-shadow ring (boxShadow=%s)" % foc.get("boxShadow"))
            check((foc.get("outline") or "none") in ("none", ""),
                  "1080p movie details: focused button has no outline ring (outline=%s)" % foc.get("outline"))
            check("255, 255, 255" in (foc.get("bg") or "") or "255,255,255" in (foc.get("bg") or "").replace(" ", "")
                  or (foc.get("bg") or "").replace(" ", "") in ("#fff", "#ffffff", "white", "rgb(255,255,255)"),
                  "1080p movie details: focused button fills white (bg=%s)" % foc.get("bg"))
            check(foc.get("mutedDisplay") in ("none", "missing"),
                  "1080p movie details: the leftover Cast count is hidden (display=%s text=%r)" % (
                      foc.get("mutedDisplay"), foc.get("mutedText")))
            # Lower sections (cast / similar) scroll
            p1080.evaluate("() => { const v=document.getElementById('view'); if (v) v.scrollTop = Math.min(400, Math.max(0, v.scrollHeight - v.clientHeight)); }")
            p1080.wait_for_timeout(200)
            scrolled = p1080.evaluate("""() => {
              const v = document.getElementById('view');
              return { top: v.scrollTop, can: v.scrollHeight > v.clientHeight + 20, overflow: getComputedStyle(v).overflowY };
            }""")
            if scrolled["can"]:
                check(scrolled["top"] > 0, "1080p movie details: the lower sections scroll (scrollTop=%s)" % scrolled["top"])
            else:
                check(scrolled["overflow"] in ("auto", "scroll", "overlay"),
                      "1080p movie details: the page is ready to scroll if content is longer (overflow=%s)" % scrolled["overflow"])

            p1080.goto("http://127.0.0.1:%d/#/show/%d/Cedar%%20Harbor" % (port, slid), wait_until="domcontentloaded")
            p1080.wait_for_function(
                "() => document.documentElement.classList.contains('tv-plex-off') && document.querySelector('#view h1, #playnext, #view .list .li')",
                timeout=15000)
            p1080.wait_for_timeout(400)
            showd = p1080.evaluate(TV_DETAILS)
            check_tv_details("1080p show details", showd, scrollable=True)
            check(showd.get("title") and "Cedar Harbor" in showd["title"],
                  "1080p show details: the show title is on the page (%s)" % showd.get("title"))
            ctx1080.close()

            # Short Android TV WebView: 960x540 CSS px at DPR 2 (physical 1920x1080)
            ctx540 = br.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2, user_agent=TV_UA)
            p540 = ctx540.new_page()
            login_tv(p540)
            i540 = p540.evaluate(TV_LAYOUT)
            check_tv("540 WebView", i540, (280, 360), 160)
            check_first_row("540 WebView", i540)
            load540 = p540.evaluate(FIRST_LOAD)
            check_first_load("540 WebView", load540)
            # The 2.5.3 bug: reserve 560px on a 540px viewport made the pane height ~0
            check(i540["viewTop"] < i540["innerH"] - 160,
                  "540 WebView: reserve is not taller than the window (top=%s innerH=%s)" % (
                      i540["viewTop"], i540["innerH"]))
            p540.keyboard.press("ArrowDown")
            p540.wait_for_timeout(450)
            i540b = p540.evaluate(TV_LAYOUT)
            check_tv("540 WebView row 2", i540b, (280, 360), 160)
            check_second_row("540 WebView", i540, i540b)
            p540.goto("http://127.0.0.1:%d/#/item/%d" % (port, iid), wait_until="domcontentloaded")
            p540.wait_for_function(
                "() => document.documentElement.classList.contains('tv-plex-off') && document.querySelector('#view h1, #view .actions')",
                timeout=15000)
            p540.wait_for_timeout(400)
            det540 = p540.evaluate(TV_DETAILS)
            check_tv_details("540 WebView movie details", det540, scrollable=False, expect_cast=True)
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
