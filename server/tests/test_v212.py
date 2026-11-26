"""2.1.2: hide web header on TV; transparent tab bar; focus-follow; movie-page Play focus."""
import json, os, shutil, sys, tempfile, threading, time
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v212-"))
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
from app.version import __version__
from app import db

print("source")
check(__version__ == "2.1.2", "version is 2.1.2")
check("## 2.1.2" in ch and ch.find("## 2.1.2") < ch.find("## 2.1.1"), "CHANGELOG has 2.1.2 above 2.1.1")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")

# CSS: web header hidden only in TV plex mode
block = None
for part in tvcss.split("html.tv-mode.tv-plex .top"):
    if part.lstrip().startswith("{"):
        block = part.split("}", 1)[0]
        break
check(block is not None and "display: none" in block, "tv-plex hides header.top with display:none")
check("html.tv-mode.tv-plex .top" in tvcss, "header hide is scoped to tv-mode + tv-plex")
top_rules = [ln.strip() for ln in css.splitlines() if ".top{" in ln.replace(" ", "") or ln.strip().startswith(".top{") or "  .top{" in ln]
check(any("var(--panel)" in ln for ln in top_rules), "desktop/phone .top still has a visible panel background")
check(all("display:none" not in ln.replace(" ", "") for ln in top_rules), "desktop/phone .top rules do not hide the header")
check("#tv-top" in tvcss and "#tv-clock" in tvcss and "#tv-tabs" in tvcss, "Plex-style tabs and clock CSS remain")
check("html.tv-mode.tv-plex.tv-plex-off #tv-top" in tvcss, "tabs stay on the TV home (hidden only off-home)")

print("transparent tab bar")
top_css = tvcss.split("html.tv-mode.tv-plex #tv-top")[1].split("#tv-tabs")[0]
check("background: transparent" in top_css or "background:transparent" in top_css, "TV tab bar background is transparent")
check("rgba(22, 22, 26, .96)" not in top_css, "TV tab bar is not the solid side-menu color")
check("linear-gradient" in tvcss and "text-shadow" in tvcss, "a fade and text-shadow keep tabs/clock readable")
check("background:var(--panel)" in css and all("transparent" not in ln or "display:none" in ln.replace(" ","") for ln in top_rules),
      "desktop/phone header is unchanged (still panel, not transparent)")

print("menu and remote")
check('data-act="search"' in tvjs and 'data-act="signout"' in tvjs and 'data-act="settings"' in tvjs, "slide-out menu has Search, Sign out, Settings")
check('data-act="profile"' in tvjs and "Sign out" in tvjs, "profile row still offers Sign out")
check("key === \"ArrowUp\" && onTab" in tvjs and "openMenu" in tvjs, "Up from the tabs is handled")
check("key === \"ArrowLeft\" && onTab)" in tvjs or 'key === "ArrowLeft" && onTab' in tvjs, "Left from the tabs opens the menu")
check('cur === document.querySelector("#tv-tabs button")' not in tvjs, "Left is not limited to the first tab")
check("closest(\".side, .top, .tabbar\")" in tvjs and "filtered" in tvjs, "TV candidates drop the web header")
check("armPreview" in tvjs and "250" in tvjs, "tabs/menu activate on focus after ~250 ms")
check('act === "signout"' in tvjs and "armPreview" in tvjs, "Sign out is excluded from focus-to-open")
check("schema stays 12" in ch.lower() or "schema stays 12" in ch, "changelog says schema stays 12")

print("movie-page scroll / Play focus")
check('block: "start"' in appjs or "block: 'start'" in appjs, "afterRoute focuses Resume/Play with block start")
check("block === \"start\"" in appjs and "scrollTop = 0" in appjs, "TV.focus pin-to-top does not use scrollIntoView center")
check("apply tv-plex-off" in tvjs or "tighter #view padding" in tvjs, "tv-plex applies movie-page layout before focusing Play")
# wrapper calls syncPage before after()
wrap = tvjs[tvjs.find("TV.afterRoute = function"):tvjs.find("TV.afterRoute = function")+1200]
# ignore the signed-out early return; the details path must sync layout, then call after()
sync = wrap.find("self.syncPage()")
afters = [i for i in range(len(wrap)) if wrap.startswith("after();", i)]
check(sync != -1 and any(i > sync for i in afters), "syncPage runs before the original afterRoute on the details path")
check("isDetailView" in wrap and "scrollTop = 0" in wrap, "details route pins #view to the top")

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "12", "fresh migrate stays on schema 12 (got %s)" % ver)

# --- live TV UA regression (2.1-layout plex chrome) ---
print("live TV UA movie page")
PREVIEW = ROOT.parent / "preview-data"
TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.0.2 AndroidTV")

def run_live():
    if not PREVIEW.exists():
        check(False, "preview-data is present for the TV UA test")
        return
    live = Path(tempfile.mkdtemp(prefix="ms-v212-live-"))
    shutil.copytree(PREVIEW, live, dirs_exist_ok=True)
    os.environ["MS_DATA_DIR"] = str(live)
    # re-import is messy; spawn uvicorn with env in a subprocess-like thread after setting env
    # The already-imported app bound MS_DATA_DIR at first import. Use a fresh port with
    # the preview copy by starting a child python.
    return live

# Use a child process so the preview DB is a clean copy and app is loaded with that data dir.
import subprocess, socket
live_dir = Path(tempfile.mkdtemp(prefix="ms-v212-live-"))
if PREVIEW.exists():
    # copy db + thumbs needed to render a title
    for name in os.listdir(PREVIEW):
        src, dst = PREVIEW / name, live_dir / name
        if name in ("transcode", "prefetch"):
            dst.mkdir(exist_ok=True)
            continue
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    starter = r'''
import os, sys
os.environ["MS_DATA_DIR"] = %r
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)
sys.path.insert(0, %r)
from app import db, keys, settings, server
import uvicorn
db.migrate(); keys.ensure()
print("READY", flush=True)
uvicorn.run(server.app, host="127.0.0.1", port=%d, log_level="warning")
''' % (str(live_dir), str(ROOT), port)
    proc = subprocess.Popen([sys.executable, "-c", starter], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ready = False
    t0 = time.time()
    while time.time() - t0 < 20:
        line = proc.stdout.readline() if proc.poll() is None else ""
        if line and "READY" in line:
            ready = True
            break
        if proc.poll() is not None:
            rest = proc.stdout.read()
            print("server exited:", rest[-500:])
            break
        time.sleep(0.05)
    # even without READY printed, health may be up
    import urllib.request, urllib.error
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)
    check(ready, "isolated preview server started")
    if ready:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            check(False, "playwright is available (%s)" % e)
            proc.terminate()
            proc.wait(timeout=5)
            print("failed", failed)
            sys.exit(1 if failed else 0)

        MOCK = """(() => { const caps = {quality:"ask", wifi_only:true, storage:"internal", external_available:false, lock:"device",
          device_secure:true, pin:false, registered:true, online:true, username:"admin", wipe_days:30, offline_days:30,
          last_sync:Math.floor(Date.now()/1000)-600};
          window.MSAndroid = { offlineCaps:()=>JSON.stringify(caps), downloads:()=>"[]",
            storageInfo:()=>JSON.stringify({used:0, free:20e9, total:32e9}),
            posterData:()=>"", isTv:()=>true, pipAvailable:()=>false, signingOut(){}, playing(){}, player(){}, state(){},
            pip(){}, playOffline(){}, call(id,name,args){ setTimeout(()=>window.__msResolve(id,true,JSON.stringify({ok:true})),100); } };
        })();"""
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True,
                                   args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
            ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
            ctx.add_init_script(MOCK)
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
            page.wait_for_function("() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')", timeout=15000)
            page.goto("http://127.0.0.1:%d/#/home" % port, wait_until="domcontentloaded")
            page.wait_for_selector("#tv-tabs, #view .card", timeout=20000)
            page.wait_for_timeout(600)
            home = page.evaluate("""() => {
              const top = document.getElementById('tv-top');
              return {
                tvPlex: document.documentElement.classList.contains('tv-plex'),
                topBg: top ? getComputedStyle(top).backgroundColor : '',
                topDisplay: top ? getComputedStyle(top).display : 'missing'
              };
            }""")
            check(home["tvPlex"], "home uses the 2.1 Plex TV layout (tv-plex)")
            # transparent: computed bg should be fully transparent (gradient is on ::before)
            bg = (home["topBg"] or "").replace(" ", "")
            check(bg in ("rgba(0,0,0,0)", "transparent", "rgba(0,0,0,0.0)") or "0,0,0,0" in bg,
                  "TV tab bar computed background is transparent (%s)" % home["topBg"])

            href = page.evaluate("""() => {
              const c = document.querySelector('#view .card[data-href*="#/item/"], #view .card[data-href*="#/show/"]');
              return c ? c.getAttribute('data-href') : '';
            }""")
            check(bool(href), "a title card is on the home screen (%s)" % href)
            if href:
                page.evaluate("(h) => { location.hash = h; }", href)
                page.wait_for_selector("#play, #resume", timeout=20000)
                page.wait_for_timeout(500)
                st = page.evaluate("""() => {
                  const v = document.getElementById('view');
                  const act = document.getElementById('resume') || document.getElementById('play');
                  const r = act ? act.getBoundingClientRect() : null;
                  const cs = v ? getComputedStyle(v) : null;
                  return {
                    hash: location.hash,
                    plexOff: document.documentElement.classList.contains('tv-plex-off'),
                    tvPlex: document.documentElement.classList.contains('tv-plex'),
                    tvMode: document.documentElement.classList.contains('tv-mode'),
                    scrollTop: v ? v.scrollTop : -1,
                    padTop: cs ? cs.paddingTop : '',
                    focusId: document.activeElement && document.activeElement.id,
                    actId: act && act.id,
                    actTop: r && r.top,
                    actBottom: r && r.bottom,
                    vh: window.innerHeight
                  };
                }""")
                print("    details", st)
                check(st["tvMode"] and st["tvPlex"] and st["plexOff"], "movie page uses 2.1 TV layout with home chrome off")
                pad = float(str(st["padTop"]).replace("px", "") or 999)
                check(pad < 80, "movie page is not laid out with the 560px home padding (pad=%s)" % st["padTop"])
                check(st["scrollTop"] <= 16, "#view is scrolled to the top (scrollTop=%s)" % st["scrollTop"])
                check(st["focusId"] in ("resume", "play"), "focus is on Resume or Play (got %s)" % st["focusId"])
                check(st["actTop"] is not None and st["actTop"] >= 0 and st["actBottom"] <= st["vh"],
                      "Play/Resume is on screen (top=%s bottom=%s vh=%s)" % (st["actTop"], st["actBottom"], st["vh"]))
            br.close()
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
else:
    check(False, "preview-data exists for the TV UA regression test")

print("failed", failed)
sys.exit(1 if failed else 0)
