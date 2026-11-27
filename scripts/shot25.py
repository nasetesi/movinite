"""Preview screenshots for 2.5: Continue watching with shared titles (desktop, phone, offline detail)."""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/workspace/media-server/v25/media-server")
OUT = Path("/workspace/media-server/v25/previews")
OUT.mkdir(parents=True, exist_ok=True)
DATA = Path("/tmp/ms-v25-preview-data")
PORT = 8250
BASE = "http://127.0.0.1:%d" % PORT
FORBIDDEN = re.compile(r"Sunset|Waimea|tukuia|nasetesi|naseaho|Adore|Adoration|/workspace/|192\.168\.", re.I)
PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

if DATA.exists():
    import shutil
    shutil.rmtree(DATA)
DATA.mkdir(parents=True)
(DATA / "thumbs").mkdir()
os.environ["MS_DATA_DIR"] = str(DATA)
os.environ["MS_SESSION_DAYS"] = "30"
sys.path.insert(0, str(ROOT))

from app import auth, db, keys, server, settings  # noqa: E402
import uvicorn  # noqa: E402


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def paint_poster(title, bg, path, kind="poster"):
    w, h = (1280, 720) if kind == "backdrop" else (400, 600)
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    # soft vignette bars
    for i in range(40):
        shade = tuple(max(0, c - i * 2) for c in bg)
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=shade)
    f = font(42 if kind == "backdrop" else 36)
    # word wrap
    words, lines, cur = title.split(), [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=f) < w - 48:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    text = "\n".join(lines)
    bbox = d.multiline_textbbox((0, 0), text, font=f, align="center", spacing=8)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.multiline_text(((w - tw) / 2, (h - th) / 2), text, font=f, fill=(245, 236, 255),
                     align="center", spacing=8)
    im.save(path, "JPEG", quality=90)


def poster_name(title, bg, kind="poster"):
    tmp = DATA / "thumbs" / ("_%s.jpg" % kind)
    paint_poster(title, bg, tmp, kind)
    h = hashlib.sha1((title + kind + str(bg)).encode()).hexdigest()
    name = h + ".jpg"
    dest = DATA / "thumbs" / name
    tmp.replace(dest)
    return name


def setup():
    db.migrate()
    keys.ensure()
    if not db.row("SELECT id FROM users WHERE username=?", ("admin",)):
        auth.create_user("admin", "TestPass14!", is_admin=True)
    settings.put("server_name", "North")
    now = int(time.time())
    media = DATA / "media"
    media.mkdir(exist_ok=True)
    colors = {
        "Northstar": (72, 28, 96),
        "The Last Light": (36, 48, 112),
        "Harbor Night": (28, 36, 64),
        "Finished Voyage": (80, 40, 40),
    }
    posters = {t: poster_name(t, c) for t, c in colors.items()}
    backs = {t: poster_name(t, c, "backdrop") for t, c in colors.items()}
    clip = media / "northstar.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
    with db.tx() as c:
        c.execute("DELETE FROM remote_progress")
        c.execute("DELETE FROM progress")
        c.execute("DELETE FROM remote_items")
        c.execute("DELETE FROM remote_libraries")
        c.execute("DELETE FROM peers")
        c.execute("DELETE FROM items")
        c.execute("DELETE FROM libraries")
        c.execute("INSERT INTO libraries(name, kind, path, scan_interval_h, created_at) VALUES(?,?,?,?,?)",
                  ("Movies", "movies", str(media), 0, now))
        lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO items(library_id, path, media_type, kind, title, sort_title, year, duration, added_at, probed, tmdb_id, poster) "
                  "VALUES(?,?, 'video','movie',?,?,?,7200,?,1,?,?)",
                  (lid, str(clip), "Northstar", "Northstar", 2020, now, 90001, posters["Northstar"]))
        c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  ("srv-harbor", "Harbor", "http://192.0.2.10:8099", "ab" * 32, "incoming", "active", now, now))
        harbor = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  ("srv-light", "Lighthouse", "http://192.0.2.11:8099", "cd" * 32, "incoming", "revoked", now, now))
        light = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count, last_sync) "
                  "VALUES(?,?,?,?,?,?)", (harbor, 7, "Movies", "movies", 3, now))
        hlid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count, last_sync) "
                  "VALUES(?,?,?,?,?,?)", (light, 3, "Movies", "movies", 1, now))
        llid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        rows = [
            (hlid, 101, "Northstar", 2020, 90001, 7200),
            (hlid, 102, "The Last Light", 2019, 90002, 5400),
            (llid, 201, "Harbor Night", 2016, 90006, 5100),
        ]
        ids = {}
        for rl, rid, title, year, tmdb, dur in rows:
            c.execute("INSERT INTO remote_items(remote_library_id, remote_item_id, kind, title, year, tmdb_id, sort_title, duration, poster, backdrop, added_at, updated_at) "
                      "VALUES(?,?, 'movie',?,?,?,?,?,?,?,?,?)",
                      (rl, rid, title, year, tmdb, title, dur, posters[title], backs[title], now, now))
            ids[title] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        # in-progress: Last Light 18 min, Harbor Night 40 min; Northstar progress is on both via later API or direct
        c.execute("INSERT INTO remote_progress(user_id, remote_item_id, position, duration, watched, updated_at) "
                  "VALUES(1,?,?,?,0,?)", (ids["The Last Light"], 18 * 60, 5400, now))
        c.execute("INSERT INTO remote_progress(user_id, remote_item_id, position, duration, watched, updated_at) "
                  "VALUES(1,?,?,?,0,?)", (ids["Harbor Night"], 40 * 60, 5100, now - 30))
        c.execute("INSERT INTO remote_progress(user_id, remote_item_id, position, duration, watched, updated_at) "
                  "VALUES(1,?,?,?,0,?)", (ids["Northstar"], 25 * 60, 7200, now - 10))
        c.execute("INSERT INTO progress(user_id, item_id, position, duration, watched, updated_at) "
                  "VALUES(1,1,?,?,0,?)", (25 * 60, 7200, now - 10))
    return ids


def serve():
    setup()
    threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                     daemon=True).start()
    for _ in range(80):
        try:
            urllib.request.urlopen(BASE + "/", timeout=0.3)
            return
        except Exception:
            time.sleep(0.1)
    raise SystemExit("preview server did not start")


def login(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_selector("#pair-use-pass, #loginf, #lu", timeout=20000)
    if pg.query_selector("#pair-use-pass"):
        pg.click("#pair-use-pass")
    pg.wait_for_selector("#lu", timeout=10000)
    pg.fill("#lu", "admin")
    pg.fill("#lp", "TestPass14!")
    btn = pg.query_selector("#loginf button")
    if btn:
        btn.click()
    pg.wait_for_function(
        "() => !document.getElementById('auth') || document.getElementById('auth').classList.contains('hidden')",
        timeout=15000)
    pg.goto(BASE + "/#/home", wait_until="domcontentloaded")
    pg.wait_for_selector("#view .card", timeout=20000)
    pg.wait_for_timeout(800)


def shot(pg, name):
    body = pg.inner_text("body")
    m = FORBIDDEN.search(body)
    assert not m, "forbidden string in %s: %s" % (name, m.group(0))
    path = OUT / name
    pg.screenshot(path=str(path), full_page=False, type="png")
    print("wrote", path, "size", path.stat().st_size, flush=True)


def main():
    from playwright.sync_api import sync_playwright
    serve()
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True,
                               args=["--no-sandbox", "--disable-gpu", "--disk-cache-size=1"])
        ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        pg = ctx.new_page()
        login(pg)
        pg.wait_for_selector(".strip.cw .card, .cw .card", timeout=10000)
        pg.mouse.move(20, 20)
        pg.wait_for_timeout(300)
        shot(pg, "web-home-continue-shared.png")
        hrefs = pg.evaluate("""() => {
          const cards = [...document.querySelectorAll('.strip.cw .card, .cw .card')];
          const find = (s) => {
            const c = cards.find(el => (el.innerText || '').includes(s));
            return c ? c.getAttribute('data-href') : null;
          };
          return { light: find('Last Light'), night: find('Harbor Night') };
        }""")
        if not hrefs or not hrefs.get("light"):
            raise SystemExit("Last Light card not found")
        pg.goto(BASE + "/" + hrefs["light"], wait_until="domcontentloaded")
        pg.wait_for_function("() => { const h=document.querySelector('#view h1'); return h && h.textContent.includes('Last Light'); }", timeout=15000)
        pg.wait_for_timeout(700)
        shot(pg, "web-detail-shared-resume.png")
        if not hrefs.get("night"):
            raise SystemExit("Harbor Night card not found")
        pg.goto(BASE + "/" + hrefs["night"], wait_until="domcontentloaded")
        pg.wait_for_function("() => { const h=document.querySelector('#view h1'); return h && h.textContent.includes('Harbor Night'); }", timeout=15000)
        pg.wait_for_timeout(700)
        shot(pg, "web-detail-shared-offline.png")
        ctx.close()

        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                             user_agent=PHONE_UA, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        login(pg)
        pg.wait_for_selector(".card", timeout=15000)
        pg.wait_for_timeout(600)
        shot(pg, "phone-home-continue-shared.png")
        ctx.close()
        br.close()
    print("all preview shots written")


if __name__ == "__main__":
    main()
