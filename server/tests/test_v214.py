"""2.1.4: rail-first Left, selectable top tabs, faster TV keys; keep 2.1.2 Play focus."""
import json, os, shutil, sys, tempfile, time, socket, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v214-"))
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
check(__version__ == "2.1.4", "version is 2.1.4")
check("## 2.1.4" in ch and ch.find("## 2.1.4") < ch.find("## 2.1.3"), "CHANGELOG has 2.1.4 above 2.1.3")
check("schema stays 12" in ch.split("## 2.1.3")[0].lower(), "changelog says schema stays 12")
check("192.0.2.10" in rd and "192.168.1.10" not in rd, "public examples use 192.0.2.10")
for bad in ("tukuia.com", "Waimea", "Sunset", "nasetesi", "naseaho"):
    if bad in rd:
        check(False, "README contains %s" % bad)
check("com.tukuia" not in ch.split("## 2.0.2")[0], "recent changelog does not name the private Android package")
check("2.1.4" in rd, "README mentions 2.1.4")

print("web UI unchanged")
block = None
for part in tvcss.split("html.tv-mode.tv-plex .top"):
    if part.lstrip().startswith("{"):
        block = part.split("}", 1)[0]
        break
check(block is not None and "display: none" in block, "tv-plex hides header.top with display:none")
top_rules = [ln.strip() for ln in css.splitlines() if ".top{" in ln.replace(" ", "") or ln.strip().startswith(".top{") or "  .top{" in ln]
check(any("var(--panel)" in ln for ln in top_rules), "desktop/phone .top still has a visible panel background")
check(all("display:none" not in ln.replace(" ", "") for ln in top_rules), "desktop/phone .top rules do not hide the header")
check("html.tv-mode.tv-plex.tv-plex-off #tv-top" in tvcss, "tabs stay on the TV home (hidden only off-home)")

print("visible focus + nav source")
check("#tv-tabs button.tv-focused" in tvcss and "#tv-rail button.tv-focused" in tvcss, "tabs and rail have a .tv-focused ring")
check("background: #fff" in tvcss or "background:#fff" in tvcss, "focused tab uses a solid visible pill")
check("this.on ? \"auto\" : \"smooth\"" in appjs or "this.on ? 'auto' : 'smooth'" in appjs, "TV.focus uses instant scroll on a TV")
check("block === \"start\"" in appjs and "scrollTop = 0" in appjs, "TV.focus pin-to-top does not use scrollIntoView center")
check("el.classList.add(\"tv-focused\")" in appjs, "TV.focus marks the focused chrome/card")
check("setTimeout(run, 300)" in tvjs or "setTimeout(run,300)" in tvjs, "hero updates are debounced ~300 ms")
check("preloadNeighbors" in tvjs, "neighbour hero artwork is preloaded")
check("ensureFocus" in tvjs and "isTvChrome" in tvjs, "a fallback restores focus when it is lost")
check("focusRail" in tvjs, "Left from the first poster focuses the rail")
check("this.openMenu(cur)" in tvjs, "Left on the rail still opens the slide-out")
check("openMenu(null, \"lib\")" not in tvjs and "openMenu(null, 'lib')" not in tvjs, "Libraries tab no longer opens the slide-out")
check("keepFocus: true" in tvjs or "keepFocus:true" in tvjs, "tab focus-follow keeps the tab focused")
check("armPreview" in tvjs and "250" in tvjs, "tabs/menu still activate on focus after ~250 ms")
check('act === "signout"' in tvjs and "armPreview" in tvjs, "Sign out is excluded from focus-to-open")
check('data-act="search"' in tvjs and 'data-act="signout"' in tvjs and 'data-act="settings"' in tvjs, "slide-out still has Search, Sign out, Settings")
wrap = tvjs[tvjs.find("TV.afterRoute = function"):tvjs.find("TV.afterRoute = function")+1200]
sync = wrap.find("self.syncPage()")
afters = [i for i in range(len(wrap)) if wrap.startswith("after();", i)]
check(sync != -1 and any(i > sync for i in afters), "syncPage runs before the original afterRoute on the details path")
check("isDetailView" in wrap and "scrollTop = 0" in wrap, "details route pins #view to the top")
check("__tvKeyMs" in tvjs, "keydown handler records timings")
# first-poster Left must not call openMenu in the same branch as firstInRow
# (rail path calls openMenu; firstInRow path calls focusRail)
idx = tvjs.find("if (key === \"ArrowLeft\" && onCard && this.firstInRow")
end = tvjs.find("if (key === \"ArrowLeft\" && onRail)", idx + 1) if idx >= 0 else -1
chunk = tvjs[idx:end] if idx >= 0 and end > idx else ""
check("focusRail" in chunk and "openMenu" not in chunk, "Left on the first poster focuses the rail (does not open the menu)")

db.migrate()
ver = db.get().execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
check(str(ver) == "12", "fresh migrate stays on schema 12 (got %s)" % ver)

print("live TV UA navigation + Play regression")
PREVIEW = ROOT.parent / "preview-data"
TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.0.2 AndroidTV")
MOCK = """(() => { const caps = {quality:"ask", wifi_only:true, storage:"internal", external_available:false, lock:"device",
  device_secure:true, pin:false, registered:true, online:true, username:"admin", wipe_days:30, offline_days:30,
  last_sync:Math.floor(Date.now()/1000)-600};
  window.MSAndroid = { offlineCaps:()=>JSON.stringify(caps), downloads:()=>"[]",
    storageInfo:()=>JSON.stringify({used:0, free:20e9, total:32e9}),
    posterData:()=>"", isTv:()=>true, pipAvailable:()=>false, signingOut(){}, playing(){}, player(){}, state(){},
    pip(){}, playOffline(){}, call(id,name,args){ setTimeout(()=>window.__msResolve(id,true,JSON.stringify({ok:true})),100); } };
})();"""

SNAP = """() => {
  const el = document.activeElement;
  const cs = el ? getComputedStyle(el) : null;
  const ring = cs && (cs.boxShadow || "") + " " + (cs.backgroundColor || "") + " " + (cs.borderColor || "");
  return {
    tag: el && el.tagName,
    id: el && el.id,
    cls: el && el.className,
    act: el && el.getAttribute && el.getAttribute("data-act"),
    rail: el && el.getAttribute && el.getAttribute("data-rail"),
    tab: el && el.getAttribute && el.getAttribute("data-tab"),
    onRail: !!(el && el.closest && el.closest("#tv-rail")),
    onTab: !!(el && el.closest && el.closest("#tv-tabs")),
    onMenu: !!(el && el.closest && el.closest("#tv-menu")),
    onCard: !!(el && el.classList && el.classList.contains("card")),
    menuOpen: document.documentElement.classList.contains("tv-menu-open"),
    focused: !!(el && el.classList && el.classList.contains("tv-focused")),
    lost: !el || el === document.body || el === document.documentElement,
    ring: ring,
    href: el && el.getAttribute && el.getAttribute("data-href"),
    keyMs: (window.__tvKeyMs || []).slice(),
  };
}"""

def start_server(data_src, root):
    live_dir = Path(tempfile.mkdtemp(prefix="ms-v214-live-"))
    for name in os.listdir(data_src):
        src, dst = data_src / name, live_dir / name
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
''' % (str(live_dir), str(root), port)
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
    import urllib.request
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)
    return proc, port, ready, live_dir

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

def login_home(page, port):
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
    page.wait_for_function("() => document.querySelectorAll('#view .card').length >= 2", timeout=20000)
    page.wait_for_timeout(400)
    page.evaluate("""() => {
      const c = document.querySelector('#view .strip .card, #view .card');
      if (c && window.TV) TV.focus(c);
      else if (c) c.focus();
      window.__tvKeyMs = [];
    }""")
    page.wait_for_timeout(80)

def press(page, key):
    page.keyboard.press(key)
    # give the handler a frame to apply focus; do not wait hundreds of ms
    page.wait_for_timeout(30)

if not PREVIEW.exists():
    check(False, "preview-data exists for the TV UA regression test")
else:
    proc, port, ready, live_dir = start_server(PREVIEW, ROOT)
    check(ready, "isolated preview server started")
    if ready:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            check(False, "playwright is available (%s)" % e)
            stop(proc)
            print("failed", failed)
            sys.exit(1 if failed else 0)

        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True,
                                   args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
            ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
            ctx.add_init_script(MOCK)
            page = ctx.new_page()
            login_home(page, port)

            st = page.evaluate(SNAP)
            check(st["onCard"] and not st["menuOpen"], "start on a poster with the slide-out closed (got %s)" % st)

            # mid-row Left stays in the row
            page.evaluate("""() => {
              const st = document.querySelector('#view .strip');
              const cards = st ? [...st.querySelectorAll('.card')] : [...document.querySelectorAll('#view .card')];
              if (cards[0] && window.TV) TV.focus(cards[0]);
              window.__tvKeyMs = [];
            }""")
            press(page, "ArrowRight")
            mid = page.evaluate(SNAP)
            check(mid["onCard"] and not mid["menuOpen"] and not mid["lost"],
                  "Right from the first poster stays on a poster (got %s)" % {k: mid[k] for k in ("onCard","onRail","menuOpen","lost","href")})
            mid_href = mid.get("href")
            press(page, "ArrowLeft")
            back = page.evaluate(SNAP)
            check(back["onCard"] and not back["menuOpen"] and not back["onRail"],
                  "mid-row Left stays in the row (got %s)" % {k: back[k] for k in ("onCard","onRail","menuOpen","href")})
            check(back.get("href") != mid_href, "mid-row Left moved to a different poster")

            # Left from first poster -> rail, menu closed
            page.evaluate("""() => {
              const st = document.querySelector('#view .strip');
              const cards = st ? [...st.querySelectorAll('.card')] : [...document.querySelectorAll('#view .card')];
              if (cards[0] && window.TV) TV.focus(cards[0]);
            }""")
            t0 = time.perf_counter()
            press(page, "ArrowLeft")
            page.wait_for_function("() => !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('#tv-rail'))", timeout=2000)
            rail_ms = (time.perf_counter() - t0) * 1000
            rail = page.evaluate(SNAP)
            check(rail["onRail"] and not rail["menuOpen"] and not rail["lost"],
                  "Left from the first poster focuses the rail with the slide-out closed")
            check(rail["focused"] or "0, 0, 0" not in (rail.get("ring") or "") or "255, 255, 255" in (rail.get("ring") or ""),
                  "rail focus is visible (ring=%s focused=%s)" % (rail.get("ring"), rail["focused"]))
            print("    first-Left-to-rail end-to-end %.1f ms" % rail_ms)

            # Left on rail -> slide-out
            press(page, "ArrowLeft")
            menu = page.evaluate(SNAP)
            check(menu["menuOpen"] and menu["onMenu"] and not menu["lost"],
                  "Left on the rail opens the slide-out (got %s)" % {k: menu[k] for k in ("menuOpen","onMenu","onRail")})

            # Right/Back from menu closes to rail
            press(page, "ArrowRight")
            closed = page.evaluate(SNAP)
            check((not closed["menuOpen"]) and (closed["onRail"] or closed["onCard"]) and not closed["lost"],
                  "Right from the slide-out closes it (got %s)" % {k: closed[k] for k in ("menuOpen","onRail","onCard","lost")})

            if not closed["onRail"]:
                page.evaluate("""() => {
                  const st = document.querySelector('#view .strip');
                  const cards = st ? [...st.querySelectorAll('.card')] : [...document.querySelectorAll('#view .card')];
                  if (cards[0] && window.TV) TV.focus(cards[0]);
                }""")
                press(page, "ArrowLeft")
            # Right from rail returns to content
            press(page, "ArrowRight")
            back2 = page.evaluate(SNAP)
            check(back2["onCard"] and not back2["menuOpen"], "Right from the rail returns to a poster")

            # Up from first row -> tabs
            page.evaluate("""() => {
              const st = document.querySelector('#view .strip');
              const cards = st ? [...st.querySelectorAll('.card')] : [...document.querySelectorAll('#view .card')];
              if (cards[0] && window.TV) TV.focus(cards[0]);
            }""")
            press(page, "ArrowUp")
            tab = page.evaluate(SNAP)
            check(tab["onTab"] and not tab["menuOpen"] and not tab["lost"],
                  "Up from the first row focuses a top tab (got %s)" % {k: tab[k] for k in ("onTab","tab","menuOpen","lost","focused")})
            check(tab["focused"] or "255, 255, 255" in (tab.get("ring") or "") or "rgb(255, 255, 255)" in (tab.get("ring") or ""),
                  "tab focus is visible (ring=%s focused=%s tab=%s)" % (tab.get("ring"), tab["focused"], tab.get("tab")))

            # tab Right / Left
            start_tab = tab.get("tab")
            press(page, "ArrowRight")
            tab2 = page.evaluate(SNAP)
            check(tab2["onTab"] and tab2.get("tab") and tab2.get("tab") != start_tab,
                  "Right moves to another tab (from %s to %s)" % (start_tab, tab2.get("tab")))
            press(page, "ArrowLeft")
            tab3 = page.evaluate(SNAP)
            check(tab3["onTab"] and tab3.get("tab") == start_tab,
                  "Left returns to the previous tab (%s)" % tab3.get("tab"))

            # Left from first tab -> rail
            page.evaluate("""() => {
              const t = document.querySelector('#tv-tabs button');
              if (t && window.TV) TV.focus(t);
            }""")
            press(page, "ArrowLeft")
            from_tab = page.evaluate(SNAP)
            check(from_tab["onRail"] and not from_tab["menuOpen"],
                  "Left from the first tab goes to the rail, not the slide-out")

            # focus never lost over a key sequence
            lost = page.evaluate("""() => {
              const keys = ["ArrowDown","ArrowRight","ArrowRight","ArrowLeft","ArrowUp","ArrowRight","ArrowLeft","ArrowDown"];
              const lostAt = [];
              // run via dispatched events through TV.onKey path
              return lostAt;
            }""")
            seq = ["ArrowDown", "ArrowRight", "ArrowRight", "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowLeft", "ArrowDown", "ArrowLeft", "ArrowRight"]
            lost_n = 0
            page.evaluate("""() => {
              const c = document.querySelector('#view .strip .card, #view .card');
              if (c && window.TV) TV.focus(c);
              window.__tvKeyMs = [];
            }""")
            for k in seq:
                press(page, k)
                s = page.evaluate(SNAP)
                if s["lost"] or not (s["onCard"] or s["onTab"] or s["onRail"] or s["onMenu"]):
                    lost_n += 1
                    print("    lost after", k, s)
            check(lost_n == 0, "focus was never lost during a 10-key walk (lost=%d)" % lost_n)

            times = page.evaluate("() => (window.__tvKeyMs || []).slice()")
            if times:
                avg = sum(times) / len(times)
                mx = max(times)
                print("    keydown handler times ms: n=%d avg=%.1f max=%.1f all=%s" % (len(times), avg, mx, [round(x, 1) for x in times]))
                check(avg < 100, "average keydown handler time is under 100 ms (avg=%.1f)" % avg)
                check(mx < 250, "no single keydown handler exceeded 250 ms (max=%.1f)" % mx)
            else:
                check(False, "keydown timings were recorded")

            # 2.1.2 movie-page Play regression
            href = page.evaluate("""() => {
              const c = document.querySelector('#view .card[data-href*="#/item/"], #view .card[data-href*="#/show/"]');
              return c ? c.getAttribute('data-href') : '';
            }""")
            check(bool(href), "a title card is on the home screen (%s)" % href)
            if href:
                page.evaluate("(h) => { location.hash = h; }", href)
                page.wait_for_selector("#play, #resume", timeout=20000)
                page.wait_for_timeout(400)
                st = page.evaluate("""() => {
                  const v = document.getElementById('view');
                  const act = document.getElementById('resume') || document.getElementById('play');
                  const r = act ? act.getBoundingClientRect() : null;
                  const cs = v ? getComputedStyle(v) : null;
                  return {
                    plexOff: document.documentElement.classList.contains('tv-plex-off'),
                    tvPlex: document.documentElement.classList.contains('tv-plex'),
                    tvMode: document.documentElement.classList.contains('tv-mode'),
                    scrollTop: v ? v.scrollTop : -1,
                    padTop: cs ? cs.paddingTop : '',
                    focusId: document.activeElement && document.activeElement.id,
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
    stop(proc)

# Optional: 2.1.3 handler-equivalent end-to-end timing on the same data, if the 2.1.3 tree is present.
V213 = ROOT.parent.parent / "v213" / "media-server"
if PREVIEW.exists() and V213.exists():
    print("2.1.3 timing comparison")
    proc, port, ready, live_dir = start_server(PREVIEW, V213)
    if ready:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                br = p.chromium.launch(channel="chrome", headless=True,
                                       args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
                ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
                ctx.add_init_script(MOCK)
                page = ctx.new_page()
                login_home(page, port)
                # wrap onKey to measure 2.1.3
                page.evaluate("""() => {
                  window.__tvKeyMs = [];
                  if (!window.TV || !TV.onKey) return;
                  const orig = TV.onKey.bind(TV);
                  TV.onKey = function (e) {
                    const t0 = performance.now();
                    const r = orig(e);
                    (window.__tvKeyMs = window.__tvKeyMs || []).push(performance.now() - t0);
                    return r;
                  };
                  const c = document.querySelector('#view .strip .card, #view .card');
                  if (c && window.TV) TV.focus(c);
                }""")
                for k in ["ArrowRight", "ArrowRight", "ArrowLeft", "ArrowLeft", "ArrowDown", "ArrowUp"]:
                    press(page, k)
                times = page.evaluate("() => (window.__tvKeyMs || []).slice()")
                if times:
                    avg = sum(times) / len(times)
                    mx = max(times)
                    print("    2.1.3 keydown handler times ms: n=%d avg=%.1f max=%.1f all=%s" % (len(times), avg, mx, [round(x, 1) for x in times]))
                else:
                    print("    2.1.3 timings were not recorded (onKey wrap missed)")
                # also note whether Left from first poster opened the menu (the 2.1.3 bug)
                page.evaluate("""() => {
                  const st = document.querySelector('#view .strip');
                  const cards = st ? [...st.querySelectorAll('.card')] : [...document.querySelectorAll('#view .card')];
                  if (cards[0] && window.TV) TV.focus(cards[0]);
                }""")
                press(page, "ArrowLeft")
                bug = page.evaluate("""() => ({
                  menuOpen: document.documentElement.classList.contains('tv-menu-open'),
                  onRail: !!(document.activeElement && document.activeElement.closest && document.activeElement.closest('#tv-rail')),
                })""")
                print("    2.1.3 Left from first poster: menuOpen=%s onRail=%s (expected menu open, rail unfocused)" % (bug["menuOpen"], bug["onRail"]))
                br.close()
        except Exception as e:
            print("    2.1.3 comparison skipped:", e)
        stop(proc)
    else:
        stop(proc)

print("failed", failed)
sys.exit(1 if failed else 0)
