"""2.5.4: phone details top bar stays transparent while you scroll."""
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
    title, year, color = "Ember Road", 2012, (168, 78, 28)
    import hashlib
    name = hashlib.sha1((title + str(color)).encode()).hexdigest() + ".jpg"
    paint(thumbs / name, color, title)
    clip = media / "ember.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
    with db.tx() as c:
        c.execute("DELETE FROM progress")
        c.execute("DELETE FROM items")
        c.execute("DELETE FROM libraries")
        c.execute("DELETE FROM metadata")
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Movies", "movies", str(media), 0, now))
        lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("movie", 91001, title, year, LONG_OV, '["Drama"]', 128, name, name, now))
        c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster, meta_status) "
                  "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?,?)",
                  (lid, str(clip), title, title, year, now, 91001, name, "matched"))
        iid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return iid, lid

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

            br.close()
    except Exception as e:
        check(False, "live phone layout test ran (%s)" % e)
    finally:
        stop(proc)
else:
    stop(proc)

print("failed" if failed else "all ok")
sys.exit(1 if failed else 0)
