"""2.5.8: episode cards in home-style rows use the series portrait poster, not the still."""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
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


# --------------------------------------------------------------------------- static
print("== static ==")
ver = (ROOT / "app" / "version.py").read_text()
check('__version__ = "2.5.8"' in ver, "version is 2.5.8")
dbt = (ROOT / "app" / "db.py").read_text()
check("SCHEMA_VERSION = 15" in dbt, "schema stays at 15")
check('("remote_items", "show_poster", "TEXT")' in dbt, "remote_items can store show_poster without a schema bump")
tmdb = (ROOT / "app" / "tmdb.py").read_text()
check("def series_card_art(" in tmdb, "series_card_art helper exists")
check('it["show_poster"] = sm["poster"]' in tmdb, "enrich always attaches show_poster for matched episodes")
check('it["show_backdrop"] = sm["backdrop"]' in tmdb, "enrich attaches show_backdrop")
check("season_posters" in tmdb, "season posters are cached and used as a fallback")
js = (ROOT / "app" / "static" / "app.js").read_text()
check("function seriesPoster(i)" in js, "app.js has seriesPoster")
check("const useSeries = i.kind === \"episode\" && !opts.landscape" in js, "episode cards are portrait unless landscape is requested")
check("i.kind === \"episode\" || i.kind === \"video\"" not in js.split("function cardItem")[1][:800],
      "cardItem no longer forces landscape for every episode")
check('else if (lib.kind === "tv") html += L.items.length ? `<div class="strip hs">${L.items.map(i => cardItem(i)).join("")}</div>`'
      in js, "the Recently added TV row uses portrait cards, not a wide still strip")
check('if (d.episodes.length) html += `<h3>Episodes</h3><div class="grid">${d.episodes.map(i => cardItem(i)).join("")}</div>`'
      in js, "search episode results use portrait cards")
check("season.episodes.map(e =>" in js and "e.thumb" in js.split("season.episodes.map(e =>")[1][:500],
      "show details episode lists still use the still (.thumb)")
check("i.show_title || i.show || i.title" in js, "card title is the series name")
tv = (ROOT / "app" / "static" / "tv-plex.js").read_text()
check("it.show_backdrop || it.backdrop || it.show_poster || it.poster" in tv,
      "TV hero for a focused episode uses the series backdrop")
check("it.show_title || it.show || it.title" in tv, "TV hero title for an episode is the series name")
cl = (ROOT / "CHANGELOG.md").read_text()
check("## 2.5.8" in cl and "series" in cl.lower() and "poster" in cl.lower(), "changelog has a 2.5.8 section")
rd = (ROOT / "README.md").read_text()
check("**2.5.8:**" in rd, "README mentions 2.5.8")



# --------------------------------------------------------------------------- live
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
                paint(thumbs / still, (1280, 720), still_bg, "%s S01E%02d" % (title, epno))
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
        # No series poster: season poster should win
        add_show("Lone Season", 2011, 93003, (10, 10, 10), [
            (1, "Only One", (180, 40, 40)),
        ], season_poster=(20, 80, 120), series_poster=False)
        # Nothing but a still
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


print("== live ==")
DATA = Path("/tmp/ms-v258-test-data")
if DATA.exists():
    import shutil
    shutil.rmtree(DATA)
DATA.mkdir(parents=True)
os.environ["MS_DATA_DIR"] = str(DATA)
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

from app.tmdb import series_card_art  # noqa: E402
check(series_card_art({"kind": "episode", "show_poster": "show.jpg", "season_poster": "s.jpg",
                       "poster": "p.jpg", "thumb": "still.jpg"}) == "show.jpg",
      "series_card_art prefers the series poster")
check(series_card_art({"kind": "episode", "season_poster": "s.jpg", "poster": "still.jpg",
                       "thumb": "still.jpg"}) == "s.jpg",
      "series_card_art falls back to the season poster")
check(series_card_art({"kind": "episode", "poster": "local-show.jpg", "thumb": "still.jpg"}) == "local-show.jpg",
      "series_card_art uses a distinct local poster next")
check(series_card_art({"kind": "episode", "poster": "still.jpg", "thumb": "still.jpg"}) == "still.jpg",
      "series_card_art falls back to the episode still")
check(series_card_art({"kind": "movie", "poster": "m.jpg", "thumb": "t.jpg"}) == "m.jpg",
      "series_card_art leaves movie posters alone")

ids = seed(DATA)
PORT = 8272
proc, ready = start_server(DATA, PORT)
check(ready, "test server started")
try:
    api = Api(PORT)
    api.login()
    home = api.call("/api/home")
    cont = home.get("continue") or []
    titles = [i.get("show_title") or i.get("show") or i.get("title") for i in cont]
    check(any(t == "The Office" for t in titles), "home continue includes The Office")
    check(any(t == "John Adams" for t in titles), "home continue includes John Adams")
    office = next(i for i in cont if (i.get("show") or "") == "The Office" and i.get("episode") == 5)
    check(office.get("show_poster") == ids["The Office poster"],
          "The Office continue item has show_poster (the series portrait)")
    check(office.get("thumb") == ids["The Office S01E05 still"],
          "The Office continue item still has the episode still as thumb")
    check(office.get("show_poster") != office.get("thumb"),
          "series poster and episode still are different files")
    check(office.get("show_backdrop") == ids["The Office backdrop"] or office.get("backdrop") == ids["The Office backdrop"],
          "The Office item carries the series backdrop")
    check(series_card_art(office) == ids["The Office poster"],
          "series_card_art on the live item returns the series poster")

    ml = api.call("/api/mylist")
    ml_c = next(i for i in (ml.get("continue") or []) if (i.get("show") or "") == "John Adams")
    check(ml_c.get("show_poster") == ids["John Adams poster"], "mylist continue uses the John Adams series poster")

    # Recently added TV library items also get show_poster
    tv_lib = next((L for L in home.get("libraries") or [] if (L.get("library") or {}).get("kind") == "tv"), None)
    check(bool(tv_lib and tv_lib.get("items")), "home has a TV library row")
    if tv_lib:
        ep = next((i for i in tv_lib["items"] if i.get("show") == "The Office"), None)
        check(bool(ep) and ep.get("show_poster") == ids["The Office poster"],
              "Recently added TV items include the series poster")

    # Season-poster fallback
    lone = api.call("/api/items/%d" % ids["Lone Season S01E01"])
    check(not lone.get("show_poster"), "Lone Season has no series poster")
    check(lone.get("season_poster") == ids["Lone Season season"], "Lone Season falls back to the season poster")
    check(series_card_art(lone) == ids["Lone Season season"], "series_card_art uses the season poster")

    stills = api.call("/api/items/%d" % ids["Still Only S01E01"])
    check(series_card_art(stills) == ids["Still Only S01E01 still"],
          "when there is no series or season poster, the still is used")

    # Show details keep stills
    show = api.call("/api/show?library_id=%d&show=%s" % (ids["_show_lib"], urllib.parse.quote("The Office")))
    eps = []
    for s in show.get("seasons") or []:
        eps.extend(s.get("episodes") or [])
    e5 = next(e for e in eps if e.get("episode") == 5)
    check(e5.get("thumb") == ids["The Office S01E05 still"],
          "the show details API still returns the episode still as thumb")

    # Fed summary uses series art as poster
    from app import fed
    summary = fed._item_summary(office)
    check(summary.get("poster") == ids["The Office poster"], "fed catalog poster for an episode is the series art")
    check(summary.get("show_poster") == ids["The Office poster"], "fed catalog includes show_poster")
    check(summary.get("thumb") == ids["The Office S01E05 still"], "fed catalog keeps the still as thumb")
    check(summary.get("show") == "The Office" and summary.get("season") == 1 and summary.get("episode") == 5,
          "fed catalog includes show/season/episode")

    from playwright.sync_api import sync_playwright
    PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    TV_UA = ("Mozilla/5.0 (Linux; Android 12; BRAVIA 4K VH2) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0.0.0 Mobile Safari/537.36 MediaServerAndroid/2.4.4 AndroidTV")
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True,
                               args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])

        # Phone home
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                             user_agent=PHONE_UA, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        login_page(page, PORT)
        page.goto("http://127.0.0.1:%d/#/home" % PORT, wait_until="domcontentloaded")
        page.wait_for_selector("#view .strip.cw .card", timeout=15000)
        page.wait_for_timeout(400)
        info = page.evaluate("""() => {
          const cards = [...document.querySelectorAll('#view .strip.cw .card')].map(c => {
            const art = c.querySelector('.art');
            const r = art ? art.getBoundingClientRect() : {width:0,height:0};
            return {
              title: (c.querySelector('.t')||{}).textContent||'',
              sub: (c.querySelector('.s')||{}).textContent||'',
              land: c.classList.contains('landscape'),
              ratio: r.height ? r.width / r.height : 0,
              bg: art ? (art.getAttribute('data-bg')||'') : '',
              bar: !!c.querySelector('.bar'),
            };
          });
          return cards;
        }""")
        office_c = next((c for c in info if "The Office" in c["title"]), None)
        adams_c = next((c for c in info if "John Adams" in c["title"]), None)
        ember_c = next((c for c in info if "Ember Road" in c["title"]), None)
        check(bool(office_c), "phone Continue Watching shows The Office")
        check(bool(adams_c), "phone Continue Watching shows John Adams")
        if office_c:
            check(not office_c["land"], "The Office card is not landscape")
            check(office_c["ratio"] < 0.85, "The Office card is tall (ratio=%.2f, expected ~2/3)" % office_c["ratio"])
            check(ids["The Office poster"] in office_c["bg"], "The Office card art is the series poster, not the still")
            check(ids["The Office S01E05 still"] not in office_c["bg"],
                  "The Office card art is not the episode still")
            check("S01E05" in office_c["sub"], "The Office subtitle includes S01E05")
            check(office_c["bar"], "The Office card keeps the progress bar")
        if adams_c:
            check(not adams_c["land"] and ids["John Adams poster"] in adams_c["bg"],
                  "John Adams card is a tall series poster")
            check("S01E01" in adams_c["sub"], "John Adams subtitle includes S01E01")
        if ember_c and office_c:
            check(abs(ember_c["ratio"] - office_c["ratio"]) < 0.12,
                  "episode and movie cards are the same size (ratios %.2f vs %.2f)" % (office_c["ratio"], ember_c["ratio"]))

        # My List page
        page.goto("http://127.0.0.1:%d/#/mylist" % PORT, wait_until="domcontentloaded")
        page.wait_for_selector("#view .card", timeout=15000)
        page.wait_for_timeout(300)
        mlinfo = page.evaluate("""() => [...document.querySelectorAll('#view .card')].map(c => ({
          title: (c.querySelector('.t')||{}).textContent||'',
          land: c.classList.contains('landscape'),
          bg: (c.querySelector('.art')||{}).getAttribute?.('data-bg')||'',
        }))""")
        oc = next((c for c in mlinfo if "The Office" in c["title"]), None)
        check(bool(oc) and not oc["land"] and ids["The Office poster"] in oc["bg"],
              "My List uses the series poster for The Office")

        # Show details list keeps stills (wide thumbs, not cardItem posters)
        page.goto("http://127.0.0.1:%d/#/show/%d/%s" % (PORT, ids["_show_lib"], "The%20Office"),
                  wait_until="domcontentloaded")
        page.wait_for_selector("#view .list .li .thumb", timeout=15000)
        page.wait_for_timeout(300)
        thumbs = page.evaluate("""() => [...document.querySelectorAll('#view .list .li .thumb')].map(t => ({
          bg: t.getAttribute('style')||t.style.backgroundImage||'',
        }))""")
        check(any(ids["The Office S01E05 still"] in (t["bg"] or "") for t in thumbs),
              "the show details episode list still uses the episode still")
        check(not any(ids["The Office poster"] in (t["bg"] or "") for t in thumbs),
              "the show details episode list does not use the series poster as the still")
        ctx.close()

        # TV home hero
        ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, user_agent=TV_UA)
        page = ctx.new_page()
        page.add_init_script("window.MSAndroid = window.MSAndroid || { isTv: () => true };")
        login_page(page, PORT)
        page.goto("http://127.0.0.1:%d/#/home" % PORT, wait_until="domcontentloaded")
        page.wait_for_selector("#tv-hero, #view .strip.cw .card", timeout=20000)
        page.evaluate("""() => {
          const c = document.querySelector('#view .strip.cw .card');
          if (c && window.TV) TV.focus(c);
        }""")
        page.wait_for_timeout(500)
        hero = page.evaluate("""() => {
          const title = (document.getElementById('tv-hero-title')||{}).textContent||'';
          const facts = (document.getElementById('tv-hero-facts')||{}).textContent||'';
          const a = document.getElementById('tv-hero-a');
          const b = document.getElementById('tv-hero-b');
          const bg = ((a && a.style.backgroundImage) || '') + ' ' + ((b && b.style.backgroundImage) || '');
          const c = document.activeElement && document.activeElement.closest
            ? document.activeElement.closest('#view .card') : document.querySelector('#view .strip.cw .card');
          const art = c && c.querySelector('.art');
          const r = art ? art.getBoundingClientRect() : {width:0,height:0};
          return {
            title, facts, bg,
            land: !!(c && c.classList.contains('landscape')),
            ratio: r.height ? r.width / r.height : 0,
            cardBg: art ? (art.getAttribute('data-bg')||'') : '',
            cardTitle: (c && c.querySelector('.t') && c.querySelector('.t').textContent) || '',
          };
        }""")
        check("The Office" in hero["title"] or "John Adams" in hero["title"] or "Ember Road" in hero["title"],
              "TV hero has a title (%r)" % hero["title"])
        # Focus first continue card, which should be The Office S01E05 (newest)
        if "The Office" in (hero["title"] or "") or "The Office" in (hero.get("cardTitle") or ""):
            check("The Office" in hero["title"], "TV hero title for an Office episode is the series name, not the episode")
            check("S01E" in hero["facts"], "TV hero facts include the episode code")
            check(ids["The Office backdrop"] in hero["bg"], "TV hero uses the series backdrop")
            check(ids["The Office S01E05 still"] not in hero["bg"], "TV hero does not use the episode still as the backdrop")
            check(not hero["land"] and ids["The Office poster"] in hero["cardBg"],
                  "TV Continue Watching card is the series poster")
            check(hero["ratio"] < 0.85, "TV episode card is tall (ratio=%.2f)" % hero["ratio"])
        ctx.close()

        # Desktop
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = ctx.new_page()
        login_page(page, PORT)
        page.goto("http://127.0.0.1:%d/#/home" % PORT, wait_until="domcontentloaded")
        page.wait_for_selector("#view .strip.cw .card", timeout=15000)
        page.wait_for_timeout(300)
        dinfo = page.evaluate("""() => [...document.querySelectorAll('#view .strip.cw .card')].map(c => ({
          title: (c.querySelector('.t')||{}).textContent||'',
          sub: (c.querySelector('.s')||{}).textContent||'',
          land: c.classList.contains('landscape'),
          bg: (c.querySelector('.art')||{}).getAttribute?.('data-bg')||'',
        }))""")
        oc = next((c for c in dinfo if "The Office" in c["title"]), None)
        check(bool(oc) and not oc["land"] and ids["The Office poster"] in oc["bg"],
              "desktop Continue Watching uses the series poster for The Office")
        check(bool(oc) and "S01E05" in oc["sub"] and "Basketball" in oc["sub"],
              "desktop subtitle includes S01E05 and the episode name")
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
