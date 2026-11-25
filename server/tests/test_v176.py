"""1.7.6: themed now-playing chrome, auto-hiding X, beat visualizer, per-user playlists.

    python3 tests/test_v176.py
"""
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-v176-")
os.environ["MS_DATA_DIR"] = TMP + "/data"

from app import auth, db, playlists, server, settings  # noqa: E402
from app.version import __version__  # noqa: E402
from fastapi import HTTPException  # noqa: E402

fails = []
U = {"id": 1, "is_admin": 1}
U2 = {"id": 2, "is_admin": 0}


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def add_track(lib, title, artist="Tester", album="Demo", poster=None, n=1):
    i = None
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO items(library_id,path,media_type,kind,title,sort_title,artist,album,album_artist,"
            "track,duration,size,mtime,added_at,probed,poster) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (lib, "/srv/music/%s-%s-%s.m4a" % (album, title, time.time()), "audio", "track",
             title, title.lower(), artist, album, artist, n, 180, 1000, time.time(),
             int(time.time()), poster),
        )
        i = cur.lastrowid
    return i


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 6), "version is 1.7.6 or later")
    check((HERE.parent / "install.sh").is_file() and (HERE.parent / "update.sh").is_file(),
          "install.sh and update.sh are still in the tree")
    js = (HERE.parent / "app/static/app.js").read_text()
    css = (HERE.parent / "app/static/style.css").read_text()
    html = (HERE.parent / "app/static/index.html").read_text()
    ver = (HERE.parent / "app/version.py").read_text()
    srv = (HERE.parent / "app/server.py").read_text()
    ch = (HERE.parent / "CHANGELOG.md").read_text()

    print("version / cache-busting")
    check(tuple(int(x) for x in __import__("re").search(r'__version__ = "([0-9.]+)"', ver).group(1).split(".")) >= (1, 7, 6), "version.py is 1.7.6 or later")
    html_resp = server._index_response()
    body = html_resp.body.decode()
    check(('app.js?v=%s"' % __version__) in body and ('style.css?v=%s"' % __version__) in body,
          "HTML stamps assets with ?v=%s" % __version__)
    check('serviceWorker.register("/sw.js?v=%s")' % __version__ in body,
          "service worker registered with ?v=%s" % __version__)
    sw = server.service_worker()
    swb = sw.body.decode() if not isinstance(sw.body, str) else sw.body
    if isinstance(swb, bytes):
        swb = swb.decode()
    check("const V='%s'" % __version__ in swb or 'const V="%s"' % __version__ in swb,
          "sw.js carries %s" % __version__)
    check("## 1.7.6" in ch, "CHANGELOG keeps the 1.7.6 entry")

    print("themed now-playing chrome")
    bar = html[html.index('id="audiobar"'):html.index('id="eqpanel"')]
    check("&#10005;" not in bar, "close is not a plain unicode X")
    check('id="ab-close"' in bar and "stroke=\"currentColor\"" in bar[bar.index('id="ab-close"'):],
          "close is an outlined SVG in the theme")
    check('id="ab-eq"' in bar and "stroke=\"currentColor\"" in bar[bar.index('id="ab-eq"'):bar.index('id="ab-close"')]
          and "stroke-width=\"1.75\"" in bar[bar.index('id="ab-eq"'):bar.index('id="ab-close"')],
          "EQ uses the outlined 24px-grid stroke language")
    check('class="iconbtn ab-tool"' in bar[bar.index('id="ab-close"')-80:bar.index('id="ab-close"')+40]
          or 'class="iconbtn ab-tool" id="ab-close"' in bar,
          "close uses the same ab-tool button style")
    check('id="ab-add"' in bar and 'id="ab-viz-toggle"' in bar, "add-to-playlist and visualizer toggle are in the bar")
    check("#ab-prev,#ab-next{color:var(--acc-text);opacity:1" in css
          and "#ab-prev:disabled,#ab-next:disabled{opacity:.45" in css,
          "prev and next share the same colour and disabled opacity")
    prev = bar[bar.index('id="ab-prev"'):bar.index('id="ab-play"')]
    nxt = bar[bar.index('id="ab-next"'):bar.index("ab-seek")]
    check("M5.5 5h2.25v14H5.5zm2.75 7L18.5 18.75V5.25z" in prev
          and "M16.25 5H18.5v14h-2.25zm-2.75 7L5.5 18.75V5.25z" in nxt,
          "prev and next are mirrored SVGs of equal weight")

    print("auto-hide chrome")
    check("AF_HIDE_MS = 3000" in js and "af-chrome-off" in js and "function afChromePoke(" in js,
          "top chrome hides after 3s and a poke brings it back")
    check("html.af-open.af-chrome-off #ab-close{opacity:0;pointer-events:none}" in css.replace("\n", "")
          or "html.af-open.af-chrome-off #ab-close" in css,
          "hidden close fades with pointer-events none")
    check("transition:opacity .35s ease" in css, "chrome fade is smooth")

    print("visualizer")
    check("createAnalyser" in js and "EQ.src.connect(an)" in js, "AnalyserNode is tapped off the existing EQ source")
    chunk = js[js.index("function vizAttach"):js.index("function vizWanted")]
    check("createMediaElementSource" not in chunk, "visualizer does not call createMediaElementSource")
    check(js.count("createMediaElementSource(audio)") == 1, "only one createMediaElementSource(audio) in the page")
    check("requestAnimationFrame" in js and "document.hidden" in js and "prefers-reduced-motion" in js,
          "rAF pauses when hidden and respects reduced motion")
    check("VIZ_STORE" in js and "bassHist" in js and "pulse" in js, "bass-energy beat detection pulses the art")
    check("VIZ_HUES" in js and "[150, 55, 250]" in js and "[106, 22, 196]" in js
          and "[212, 187, 255]" in js and "shadowBlur" in js and "/ 14000" in js,
          "beat ring uses a slowly rotating theme gradient with a soft glow")
    check("LOGO_MARK = \"/static/logo-mark.png\"" in js
          and "st.classList.toggle(\"logo\", !hasArt)" in js,
          "tracks without art use the Movinite logo")
    check("html.af-open .ab-stage.logo img{" in css and "width:58%" in css
          and "background:transparent" in css[css.index("html.af-open .ab-stage.logo img{"):css.index("html.af-open .ab-stage.logo img{") + 280]
          and "box-shadow:none" in css[css.index("html.af-open .ab-stage.logo img{"):css.index("html.af-open .ab-stage.logo img{") + 280],
          "logo fallback is smaller and has no square tile")
    check("html.af-open.viz-on #ab-viz{display:block}" in css, "the ring is shown in the full player when enabled")
    check('id="ab-viz"' in html and 'id="ab-stage"' in html, "canvas and art stage are in the page")

    print("playlists UI")
    check("function viewPlaylists(" in js and "function viewPlaylist(" in js
          and "function openPlaylistSheet(" in js, "playlist list, detail and add sheet exist")
    check('option value="playlists">Playlists' in js
          and 'chip("view", "playlists", "Playlists"' in js,
          "Playlists is a Music library view on desktop and phone")
    check("data-add-pl" in js and "pointerdown" in js[js.index("function bindTrackList"):js.index("function bindTrackList")+800],
          "tracks have a + button and a long-press")
    check('method: "PUT", body: { ids }' in js and "data-rm=" in js
          and "id=\"pl-shuffle\"" in js and "id=\"pl-play\"" in js,
          "playlist detail can reorder, remove, play and shuffle")
    check('id="plsheet"' in html and ".plsheet{" in css, "add-to-playlist sheet is in the page")

    print("schema 8 / API")
    check("SCHEMA_VERSION = 8" in (HERE.parent / "app/db.py").read_text(), "SCHEMA_VERSION is 8")
    check("/api/playlists" in srv and "playlists.create" in srv, "playlist endpoints are registered")

    db.migrate()
    auth.create_user("admin", "TestPass14!", is_admin=True)
    auth.create_user("listener", "TestPass14!", is_admin=False)
    u2 = db.row("SELECT id FROM users WHERE username=?", ("listener",))
    U2["id"] = u2["id"]
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO shares(id,name,kind,remote,username,domain,options,mount_point,last_status,last_error,created_at,allow_write) "
                  "VALUES(1,'Media','smb','//x/m','t',NULL,NULL,'/tmp','mounted',NULL,?,0)", (now,))
        c.execute("INSERT INTO libraries(id,name,kind,path,share_id,scan_interval_h,created_at) "
                  "VALUES(1,'Music','music','/tmp/music',1,6,?)", (now,))
    a = add_track(1, "First Seed", "6 Pound", "6 Pound", n=1)
    b = add_track(1, "Second Seed", "6 Pound", "6 Pound", n=2)
    ctid = add_track(1, "Other Song", "Solo", "Solo", n=1)
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] == "8", "fresh install is schema 8")

    print("create / list / rename / delete")
    p = server.create_playlist({"name": "  Morning Mix  ", "item_ids": [a, b]}, u=U)
    check(p["name"] == "Morning Mix" and p["track_count"] == 2, "create trims the name and adds tracks")
    listed = server.list_playlists(u=U)
    check(len(listed) == 1 and listed[0]["id"] == p["id"] and listed[0]["track_count"] == 2,
          "list returns the user's playlist")
    try:
        server.create_playlist({"name": "morning mix"}, u=U)
        check(False, "duplicate name refused")
    except HTTPException as e:
        check(e.status_code == 409, "duplicate name is 409")
    try:
        server.create_playlist({"name": "  "}, u=U)
        check(False, "empty name refused")
    except HTTPException as e:
        check(e.status_code == 400, "empty name is 400")
    renamed = server.rename_playlist(p["id"], {"name": "Evening Mix"}, u=U)
    check(renamed["name"] == "Evening Mix", "rename works")
    empty = server.create_playlist({"name": "Empty"}, u=U)
    check(empty["track_count"] == 0, "can create an empty playlist")
    server.delete_playlist(empty["id"], u=U)
    check(all(x["id"] != empty["id"] for x in server.list_playlists(u=U)), "delete removes the playlist")

    print("add / skip duplicates / remove / reorder")
    dtl = server.playlist_detail(p["id"], u=U)
    check([t["id"] for t in dtl["tracks"]] == [a, b], "detail tracks are in add order")
    add = server.add_playlist_tracks(p["id"], {"item_id": ctid}, u=U)
    check(add["added"] == 1 and add["track_count"] == 3, "add a third track")
    again = server.add_playlist_tracks(p["id"], {"item_ids": [ctid, a]}, u=U)
    check(again["added"] == 0 and again["track_count"] == 3, "duplicates are skipped")
    dtl = server.playlist_detail(p["id"], u=U)
    ids = [t["entry_id"] for t in dtl["tracks"]]
    server.reorder_playlist(p["id"], {"ids": list(reversed(ids))}, u=U)
    dtl2 = server.playlist_detail(p["id"], u=U)
    check([t["id"] for t in dtl2["tracks"]] == [ctid, b, a], "reorder persists")
    mid = dtl2["tracks"][1]["entry_id"]
    server.remove_playlist_track(p["id"], mid, u=U)
    dtl3 = server.playlist_detail(p["id"], u=U)
    check([t["id"] for t in dtl3["tracks"]] == [ctid, a]
          and [t["position"] for t in dtl3["tracks"]] == [0, 1],
          "remove compacts positions")

    print("per-user isolation")
    other = server.create_playlist({"name": "Mine"}, u=U2)
    check(len(server.list_playlists(u=U2)) == 1 and len(server.list_playlists(u=U)) == 1,
          "each user only sees their own playlists")
    try:
        server.playlist_detail(p["id"], u=U2)
        check(False, "other user can read a private playlist")
    except HTTPException as e:
        check(e.status_code == 404, "other user gets 404 on someone else's playlist")
    try:
        server.add_playlist_tracks(p["id"], {"item_id": a}, u=U2)
        check(False, "other user can edit a private playlist")
    except HTTPException as e:
        check(e.status_code == 404, "other user cannot add to someone else's playlist")
    try:
        server.delete_playlist(other["id"], u=U)
        check(False, "user can delete someone else's playlist")
    except HTTPException as e:
        check(e.status_code == 404, "cannot delete someone else's playlist")

    print("migration backup is idempotent")
    data = Path(TMP) / "data"
    # simulate a 1.7.5 (schema 7) database
    with db.tx() as c:
        c.execute("DROP TRIGGER IF EXISTS playlists_drop_tracks")
        c.execute("DROP TRIGGER IF EXISTS items_drop_playlist_tracks")
        c.execute("DROP TABLE IF EXISTS playlist_tracks")
        c.execute("DROP TABLE IF EXISTS playlists")
        c.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
    db.migrate()
    bak = data / "media-server.db.pre-schema8"
    check(bak.is_file(), "schema 7 -> 8 writes media-server.db.pre-schema8")
    mode = stat.S_IMODE(bak.stat().st_mode)
    check(mode == 0o600, "backup mode is 600 (got %o)" % mode)
    check(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"] == "8", "migrate stamps schema 8")
    check(db.row("SELECT name FROM sqlite_master WHERE type='table' AND name='playlists'"),
          "playlists table exists after upgrade")
    # playlist rows from before the drop are gone (we dropped tables), that's expected
    first_mtime = bak.stat().st_mtime
    first_size = bak.stat().st_size
    time.sleep(1.05)
    db.migrate()
    check(bak.stat().st_mtime == first_mtime and bak.stat().st_size == first_size,
          "a second migrate does not overwrite the backup")
    check(int(db.row("SELECT value FROM meta WHERE key='schema_version'")["value"]) == 8,
          "migrate stays at schema 8")

    # user rows survive the upgrade path
    check(db.row("SELECT username FROM users WHERE id=1")["username"] == "admin", "users survive the schema 8 upgrade")


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
raise SystemExit(1 if fails else 0)
