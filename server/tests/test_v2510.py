"""2.5.10: posters everywhere an episode, show or season image appears."""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = []


def check(cond, msg):
    if cond:
        print("  ok:", msg)
    else:
        print("FAIL:", msg)
        FAILED.append(msg)


print("== static ==")
ver = (ROOT / "app" / "version.py").read_text()
check('__version__ = "2.5.10"' in ver, "version is 2.5.10")
dbt = (ROOT / "app" / "db.py").read_text()
check("SCHEMA_VERSION = 15" in dbt, "schema stays at 15")
js = (ROOT / "app" / "static" / "app.js").read_text()
check("function seriesPoster(i)" in js, "app.js has seriesPoster")
check("function seriesPosterOnly(i)" in js, "app.js has seriesPosterOnly")
check("const epPortrait = it.kind === \"episode\" ? seriesPosterOnly(it) : \"\"" in js,
      "episode details prefer portrait series art")
check('const land = it.kind === "episode" || it.kind === "video"' not in js,
      "viewItem no longer forces landscape for every episode")
check("it.show_backdrop || it.backdrop" in js, "episode details use the series backdrop")
check("seriesPoster(e)" in js.split("season.episodes.map(e =>")[1][:800],
      "show details episode lists use seriesPoster")
check('class="li ep"' in js, "show episode rows have the ep list class")
check("ep-code" in js, "show episode rows show SxxExx")
check("seriesPoster(it) || it.poster || it.thumb" in js, "now-playing cards use seriesPoster")
check("seriesPoster(n) || seriesPoster(P.it)" in js, "Up Next uses series art for episodes")
css = (ROOT / "app" / "static" / "style.css").read_text()
check(".detail .poster.series:not(.thumb){width:min(58vw,260px)" in css, "phone episode posters are about 55–60% wide")
check(".detail .poster:not(.landscape):not(.square):not(.series)" in css,
      "movie poster sizes exclude .series so they stay unchanged")
check("width:min(70vw,300px)" in css, "phone movie poster size is still min(70vw, 300px)")
check(".li.ep .thumb.portrait" in css and "aspect-ratio:2/3" in css, "show episode list thumbs are 2:3")
tvcss = (ROOT / "app" / "static" / "tv-plex.css").read_text()
check(".list .li.ep .thumb.portrait" in tvcss and "2 / 3" in tvcss, "TV show episode list thumbs are 2:3")
srv = (ROOT / "app" / "server.py").read_text()
check("tmdb.enrich(eps)" in srv, "/api/show enriches episodes with series art")
check("tmdb.enrich([nxt])" in srv, "the next-episode payload is enriched")
cl = (ROOT / "CHANGELOG.md").read_text()
check("## 2.5.10" in cl and "episode details" in cl.lower() and "poster" in cl.lower(),
      "changelog has a 2.5.10 section")
rd = (ROOT / "README.md").read_text()
check("**2.5.10:**" in rd, "README mentions 2.5.10")


def paint(path, size, bg, title):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36 if size[0] < 800 else 48)
    except Exception:
        f = ImageFont.load_default()
    d.multiline_text((24, size[1] // 2 - 20), title, font=f, fill=(245, 236, 255))
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
    ids = {}
    with db.tx() as c:
        for table in ("progress", "home_pins", "items", "libraries", "metadata", "show_matches", "tmdb_episodes"):
            c.execute("DELETE FROM %s" % table)
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Movies", "movies", str(media), 0, now))
        lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        name = hashlib.sha1(b"Ember Road").hexdigest() + ".jpg"
        paint(thumbs / name, (400, 600), (168, 78, 28), "Ember Road")
        clip = media / "ember.mp4"
        clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
        c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,runtime,poster,backdrop,fetched_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("movie", 91001, "Ember Road", 2012, "A film.", '["Drama"]', 128, name, name, now))
        c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, "
                  "probed, tmdb_id, poster, meta_status) VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?,?)",
                  (lid, str(clip), "Ember Road", "Ember Road", 2012, now, 91001, name, "matched"))
        ids["Ember Road"] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids["ember_poster"] = name
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Shows", "tv", str(media), 0, now))
        slid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        ids["_show_lib"] = slid
        uid = c.execute("SELECT id FROM users WHERE username=?", ("admin",)).fetchone()[0]

        def add_show(title, year, tid, poster_bg, eps, season_poster=None, series_poster=True):
            poster = hashlib.sha1((title + "poster").encode()).hexdigest() + ".jpg"
            if series_poster:
                paint(thumbs / poster, (400, 600), poster_bg, title)
            back = hashlib.sha1((title + "back").encode()).hexdigest() + ".jpg"
            paint(thumbs / back, (1280, 720), poster_bg, title + " backdrop")
            extra = "{}"
            if season_poster:
                spn = hashlib.sha1((title + "s1").encode()).hexdigest() + ".jpg"
                paint(thumbs / spn, (400, 600), season_poster, title + " S1")
                extra = json.dumps({"season_posters": {"1": spn}})
                ids[title + " season"] = spn
            c.execute("INSERT INTO metadata(kind,tmdb_id,title,year,overview,genres,poster,backdrop,fetched_at,extra) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      ("tv", tid, title, year, "A show.", '["Drama"]',
                       poster if series_poster else None, back, now, extra))
            c.execute("INSERT INTO show_matches(library_id, show, tmdb_id, status, checked_at) VALUES(?,?,?,?,?)",
                      (slid, title, tid, "matched", now))
            ids[title + " poster"] = poster if series_poster else None
            ids[title + " backdrop"] = back
            for epno, epname, still_bg in eps:
                still = hashlib.sha1(("%s still %d" % (title, epno)).encode()).hexdigest() + ".jpg"
                paint(thumbs / still, (1280, 720), still_bg, "%s S01E%02d STILL" % (title, epno))
                path = media / ("%s-s01e%02d.mp4" % (title.lower().replace(" ", ""), epno))
                path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
                c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, "
                          "added_at, probed, show, season, episode, poster, thumb, meta_status) "
                          "VALUES(?,?, 'video','episode',?,?,?,2400,?,1,?,?,?,?,?,?)",
                          (slid, str(path), epname, "%s S01E%02d" % (title, epno), year, now,
                           title, 1, epno, still, still, "matched"))
                eid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                ids["%s S01E%02d" % (title, epno)] = eid
                ids["%s S01E%02d still" % (title, epno)] = still
                c.execute("INSERT INTO tmdb_episodes(tv_id, season, episode, name, still) VALUES(?,?,?,?,?)",
                          (tid, 1, epno, epname, still))
            return ids

        add_show("The Office", 2005, 93001, (40, 70, 50), [
            (4, "The Alliance", (200, 180, 40)),
            (5, "Basketball", (210, 160, 30)),
        ])
        add_show("John Adams", 2008, 93002, (90, 50, 30), [
            (1, "Join or Die", (60, 80, 140)),
        ])
        add_show("Lone Season", 2011, 93003, (10, 10, 10), [
            (1, "Only One", (180, 40, 40)),
        ], season_poster=(20, 80, 120), series_poster=False)
        add_show("Still Only", 2012, 93004, (10, 10, 10), [
            (1, "The Clip", (30, 30, 180)),
        ], series_poster=False)

        c.execute("INSERT INTO progress(user_id, item_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                  (uid, ids["The Office S01E05"], 600, 2400, now + 90))
        c.execute("INSERT INTO progress(user_id, item_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                  (uid, ids["John Adams S01E01"], 500, 2400, now + 80))
        c.execute("INSERT INTO progress(user_id, item_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                  (uid, ids["The Office S01E04"], 400, 2400, now + 70))
        c.execute("INSERT INTO progress(user_id, item_id, position, duration, updated_at) VALUES(?,?,?,?,?)",
                  (uid, ids["Ember Road"], 800, 7200, now + 10))
        c.execute("INSERT INTO progress(user_id, item_id, position, duration, watched, updated_at) VALUES(?,?,?,?,?,?)",
                  (uid, ids["Lone Season S01E01"], 0, 2400, 1, now + 5))
    return ids


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


class Api:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port
        self.cj = urllib.request.HTTPCookieProcessor()
        self.op = urllib.request.build_opener(self.cj)

    def call(self, path, body=None):
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        with self.op.open(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def login(self):
        return self.call("/api/login", {"username": "admin", "password": "TestPass14!"})


def login_page(page, port):
    page.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
    page.wait_for_selector("#pair-use-pass, #loginf, #lu", timeout=20000)
    if page.query_selector("#pair-use-pass"):
        page.click("#pair-use-pass")
        page.wait_for_selector("#lu", timeout=8000)
    page.fill("#lu", "admin")
    page.fill("#lp", "TestPass14!")
    btn = page.query_selector("#loginf button")
    if btn:
        btn.click()
    page.wait_for_function(
        "() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')",
        timeout=15000)
    page.wait_for_timeout(200)


def art_info(page, sel):
    return page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const cs = getComputedStyle(el);
          const bg = cs.backgroundImage || "";
          const r = el.getBoundingClientRect();
          return {
            cls: el.className,
            land: el.classList.contains("landscape"),
            series: el.classList.contains("series"),
            bg,
            w: r.width,
            h: r.height,
            ratio: r.height ? r.width / r.height : 0
          };
        }""", sel)


print("== live ==")
DATA = Path("/tmp/ms-v2510-test-data")
if DATA.exists():
    import shutil
    shutil.rmtree(DATA)
DATA.mkdir(parents=True)
os.environ["MS_DATA_DIR"] = str(DATA)
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

from app.tmdb import series_card_art  # noqa: E402

ids = seed(DATA)
PORT = 8274
proc, ready = start_server(DATA, PORT)
check(ready, "test server started")
try:
    api = Api(PORT)
    api.login()

    ja = api.call("/api/items/%d" % ids["John Adams S01E01"])
    check(ja.get("show_poster") == ids["John Adams poster"], "episode details API has show_poster")
    check(ja.get("thumb") == ids["John Adams S01E01 still"], "episode details API keeps the still as thumb")
    check(ja.get("show_backdrop") == ids["John Adams backdrop"] or ja.get("backdrop") == ids["John Adams backdrop"],
          "episode details API carries the series backdrop")
    check(series_card_art(ja) == ids["John Adams poster"], "series_card_art on the details item is the series poster")
    check(ja.get("show_poster") != ja.get("thumb"), "series poster and episode still are different files")

    nxt = ja.get("next")
    check(not nxt, "Join or Die has no next episode")

    office = api.call("/api/items/%d" % ids["The Office S01E04"])
    nxt = office.get("next") or {}
    check(nxt.get("episode") == 5 and nxt.get("title") == "Basketball", "next episode is S01E05")
    check(nxt.get("show_poster") == ids["The Office poster"], "next episode carries show_poster")

    show = api.call("/api/show?library_id=%d&show=%s" % (ids["_show_lib"], urllib.parse.quote("The Office")))
    eps = []
    for s in show.get("seasons") or []:
        eps.extend(s.get("episodes") or [])
    e5 = next(e for e in eps if e.get("episode") == 5)
    check(e5.get("show_poster") == ids["The Office poster"], "show details episodes include show_poster")
    check(e5.get("thumb") == ids["The Office S01E05 still"], "show details episodes still expose the still as thumb")
    check(series_card_art(e5) == ids["The Office poster"], "show-list art prefers the series poster")

    lone = api.call("/api/items/%d" % ids["Lone Season S01E01"])
    check(not lone.get("show_poster"), "Lone Season has no series poster")
    check(lone.get("season_poster") == ids["Lone Season season"], "Lone Season falls back to the season poster")

    stills = api.call("/api/items/%d" % ids["Still Only S01E01"])
    check(series_card_art(stills) == ids["Still Only S01E01 still"],
          "when there is no series or season poster, the still is used")

    health = api.call("/api/health")
    check(health.get("version") == "2.5.10", "health reports 2.5.10")

    from playwright.sync_api import sync_playwright
    PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.4.4 AndroidTV")
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True,
                               args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])

        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                             user_agent=PHONE_UA, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        login_page(page, PORT)

        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["John Adams S01E01"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(300)
        info = art_info(page, ".detail .poster")
        check(info and info["series"] and not info["land"], "phone episode details poster is portrait .series")
        check(info and ids["John Adams poster"] in (info["bg"] or ""),
              "phone episode details uses the series poster file")
        check(info and ids["John Adams S01E01 still"] not in (info["bg"] or ""),
              "phone episode details does not use the episode still")
        if info:
            check(200 <= info["w"] <= 270, "phone episode poster width is about 55–60%% of 390px (got %.1f)" % info["w"])
            check(0.62 <= info["ratio"] <= 0.72, "phone episode poster aspect is ~2:3 (got %.3f)" % info["ratio"])

        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["Ember Road"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(300)
        minfo = art_info(page, ".detail .poster")
        check(minfo and not minfo["series"] and not minfo["land"], "phone movie poster is not .series")
        if minfo:
            check(250 <= minfo["w"] <= 310, "phone movie poster keeps ~70vw/300px size (got %.1f)" % minfo["w"])
            check(minfo["w"] > (info["w"] if info else 0), "phone movie poster is wider than the episode series poster")

        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["Lone Season S01E01"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(250)
        linfo = art_info(page, ".detail .poster")
        check(linfo and linfo["series"] and ids["Lone Season season"] in (linfo["bg"] or ""),
              "phone details fall back to the season poster")

        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["Still Only S01E01"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(250)
        sinfo = art_info(page, ".detail .poster")
        check(sinfo and sinfo["land"] and not sinfo["series"],
              "phone details stay landscape when only a still is available")
        check(sinfo and ids["Still Only S01E01 still"] in (sinfo["bg"] or ""),
              "phone details last-resort art is the still")

        page.goto("http://127.0.0.1:%d/#/show/%d/%s" % (PORT, ids["_show_lib"], urllib.parse.quote("The Office")),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".list .li.ep .thumb.portrait", timeout=15000)
        page.wait_for_timeout(300)
        rows = page.evaluate(
            """() => Array.from(document.querySelectorAll('.list .li.ep')).map(li => {
              const thumb = li.querySelector('.thumb.portrait');
              const code = (li.querySelector('.ep-code') || {}).textContent || '';
              const title = (li.querySelector('.ttl b') || {}).textContent || '';
              const cs = thumb ? getComputedStyle(thumb) : {};
              const r = thumb ? thumb.getBoundingClientRect() : {width:0,height:0};
              return {code, title, bg: cs.backgroundImage || '', w: r.width, h: r.height,
                      ratio: r.height ? r.width / r.height : 0};
            })""")
        check(len(rows) >= 2, "show details lists the season's episodes")
        check(any(r["code"].replace(" ", "") == "S01E05" and "Basketball" in r["title"] for r in rows),
              "episode list shows S01E05 and the episode name")
        check(all(ids["The Office poster"] in r["bg"] for r in rows),
              "every show-list thumb uses the series poster")
        check(all(ids["The Office S01E05 still"] not in r["bg"] and ids["The Office S01E04 still"] not in r["bg"]
                  for r in rows),
              "show-list thumbs do not use episode stills")
        check(all(0.62 <= r["ratio"] <= 0.72 for r in rows), "show-list thumbs are 2:3")
        check(all(60 <= r["w"] <= 100 for r in rows),
              "phone show-list thumbs stay compact (got %s)" % [round(r["w"], 1) for r in rows])
        ctx.close()

        # TV 1920x1080 episode details
        ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
        page = ctx.new_page()
        page.add_init_script("window.MSAndroid = window.MSAndroid || { isTv: () => true };")
        login_page(page, PORT)
        page.wait_for_function("() => document.documentElement.classList.contains('tv-mode')", timeout=15000)
        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["John Adams S01E01"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(400)
        tinfo = art_info(page, ".detail .poster")
        check(tinfo and tinfo["series"] and not tinfo["land"], "TV episode details poster is portrait .series")
        check(tinfo and ids["John Adams poster"] in (tinfo["bg"] or ""),
              "TV episode details uses the series poster")
        if tinfo:
            check(tinfo["w"] <= 330, "TV episode poster stays within the first-screen size (got %.1f)" % tinfo["w"])
            check(0.62 <= tinfo["ratio"] <= 0.72, "TV episode poster aspect is ~2:3")
        # backdrop
        dbg = page.evaluate(
            """() => {
              const el = document.querySelector('.detail-bg .dbg-img');
              return el ? getComputedStyle(el).backgroundImage : '';
            }""")
        check(ids["John Adams backdrop"] in (dbg or ""), "TV episode details backdrop is the series backdrop")
        # first-screen cast was a 2.5.6 constraint; there may be no cast in this seed
        poster_bottom = page.evaluate(
            "() => { const el = document.querySelector('.detail .poster'); return el ? el.getBoundingClientRect().bottom : 0; }")
        check(poster_bottom and poster_bottom < 1080, "TV episode poster fits on the first screen")

        page.goto("http://127.0.0.1:%d/#/show/%d/%s" % (PORT, ids["_show_lib"], urllib.parse.quote("The Office")),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".list .li.ep .thumb.portrait", timeout=15000)
        page.wait_for_timeout(300)
        tvrows = page.evaluate(
            """() => Array.from(document.querySelectorAll('.list .li.ep')).map(li => {
              const thumb = li.querySelector('.thumb.portrait');
              const code = (li.querySelector('.ep-code') || {}).textContent || '';
              const bg = thumb ? getComputedStyle(thumb).backgroundImage : '';
              const r = thumb ? thumb.getBoundingClientRect() : {width:0,height:0};
              return {code, bg, ratio: r.height ? r.width / r.height : 0, w: r.width};
            })""")
        check(any(r["code"].replace(" ", "") == "S01E04" for r in tvrows), "TV show list includes S01E04")
        check(all(ids["The Office poster"] in r["bg"] for r in tvrows),
              "TV show-list thumbs use the series poster")
        check(all(0.62 <= r["ratio"] <= 0.72 for r in tvrows), "TV show-list thumbs are 2:3")
        check(all(100 <= r["w"] <= 160 for r in tvrows),
              "TV show-list thumbs stay compact (got %s)" % [round(r["w"], 1) for r in tvrows])
        ctx.close()

        # 960x540 DPR 2
        ctx = br.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2, user_agent=TV_UA)
        page = ctx.new_page()
        page.add_init_script("window.MSAndroid = window.MSAndroid || { isTv: () => true };")
        login_page(page, PORT)
        page.wait_for_function("() => document.documentElement.classList.contains('tv-mode')", timeout=15000)
        page.goto("http://127.0.0.1:%d/#/item/%d" % (PORT, ids["John Adams S01E01"]),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".detail .poster", timeout=15000)
        page.wait_for_timeout(400)
        s540 = art_info(page, ".detail .poster")
        check(s540 and s540["series"] and not s540["land"], "960x540 TV episode details poster is portrait")
        check(s540 and ids["John Adams poster"] in (s540["bg"] or ""),
              "960x540 TV episode details uses the series poster")
        if s540:
            check(0.62 <= s540["ratio"] <= 0.72, "960x540 TV episode poster aspect is ~2:3")
        ctx.close()
        br.close()
finally:
    stop(proc)

print()
if FAILED:
    print("%d failed:" % len(FAILED))
    for m in FAILED:
        print(" -", m)
    sys.exit(1)
print("all ok")
