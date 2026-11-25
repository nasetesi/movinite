"""1.7.2 / 1.7.3: phone Libraries tab is grouped with film counts and no shortcut chips; the mini
player no longer covers the last card; cache-busting forces phones to pick up new JS.

    python3 tests/test_v172.py
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-v172-")
os.environ["MS_DATA_DIR"] = TMP + "/data"

from app import server  # noqa: E402
from app.version import __version__  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 7, 2), "version is 1.7.2 or later")
    js = (HERE.parent / "app/static/app.js").read_text()
    css = (HERE.parent / "app/static/style.css").read_text()
    srv = (HERE.parent / "app/server.py").read_text()

    vl = js[js.index("async function viewLibraries"):js.index("async function viewMyList")]
    print("Libraries tab")
    check("libGroups()" in vl and "libsGrouped()" in vl and "lib-grp-h" in vl,
          "phone Libraries tab still groups libraries under each share heading")
    check("libCountText(l)" in vl, "library cards use libCountText (films, not files)")
    check("lib-subs" not in vl and "/collections" not in vl and "smart/recommended" not in vl
          and "smart/added" not in vl and "smart/top" not in vl and "Top movies" not in vl
          and "Recently added" not in vl and "Recommended" not in vl,
          "Collections / Recommended / Recently added / Top movies chips are gone")
    check("sub[l.kind]" in vl and "lib-li" in vl, "each library is just its card (name, type, count)")

    print("mini player clearance")
    check('document.documentElement.classList.add("ab-open")' in js
          and 'document.documentElement.classList.remove("ab-open")' in js,
          "html.ab-open is set while the mini player is open and cleared when it closes")
    check("var(--abar-space" in css and "html.ab-open{--abar-space:108px}" in css,
          "phone #view padding grows by the mini-player height when music is playing")
    check("#view{padding:8px 14px calc(92px + var(--abar-space, 0px) + env(safe-area-inset-bottom))}" in css,
          "every phone page (#view) uses the same bottom padding, not just Libraries")

    print("phone mini-player progress bar")
    mq = css[css.index("1.5.1: phone layout"):]
    mq = mq[mq.index("@media (max-width:820px)"):]
    check("grid-template-columns:44px minmax(0,1fr) auto auto" in mq and "grid-template-rows:auto auto" in mq,
          "phone mini player is a two-row grid (title/controls, then seek)")
    check(".ab-seek{grid-column:1/-1;grid-row:2;min-width:0;width:100%" in mq,
          "seek row spans the full width of the mini player")
    check("#ab-cur,#ab-dur{flex:none;white-space:nowrap}" in mq,
          "elapsed and total times stay visible and do not wrap")
    check(".ab-seek input{min-width:0;flex:1 1 0;width:auto}" in mq,
          "the range input can shrink so it stays inside the bar")
    check(".audiobar{bottom:calc(62px" in mq,
          "mini player still sits above the phone tab bar")
    check(".pl-time{font-size:12px;padding:0 2px;flex:1 0 100%;order:-1}" in css,
          "full-player time sits on its own line on phones so the control buttons fit")

    print("cache-busting")
    html = server._index_response()
    body = html.body.decode()
    cc = (html.headers.get("cache-control") or "").lower()
    check("no-store" in cc and "no-cache" in cc, "HTML is no-store / no-cache: %s" % html.headers.get("cache-control"))
    check(('app.js?v=%s"' % __version__) in body and ('style.css?v=%s"' % __version__) in body,
          "asset URLs stamped with v%s" % __version__)
    check('name="movinite-version" content="%s"' % __version__ in body, "movinite-version meta tag")
    check("window.MS_VERSION='%s'" % __version__ in body or 'window.MS_VERSION="%s"' % __version__ in body,
          "window.MS_VERSION is set")
    check('serviceWorker.register("/sw.js?v=%s")' % __version__ in body, "service worker registered with ?v=%s" % __version__)

    sw = server.service_worker()
    swb = sw.body.decode() if hasattr(sw, "body") else sw.body
    if isinstance(swb, bytes):
        swb = swb.decode()
    swcc = (sw.headers.get("cache-control") or "").lower()
    check("no-store" in swcc, "sw.js is no-store: %s" % sw.headers.get("cache-control"))
    check(sw.headers.get("service-worker-allowed") == "/", "Service-Worker-Allowed: /")
    check("const V='%s'" % __version__ in swb or 'const V="%s"' % __version__ in swb, "sw.js carries this version")
    check("skipWaiting()" in swb and "clients.claim()" in swb, "new worker takes over immediately")
    check("cache:'no-store'" in swb or 'cache:"no-store"' in swb, "SW fetches HTML and JS/CSS with cache no-store")
    check(r"app\.js" in swb and r"style\.css" in swb, "SW intercepts app.js and style.css")

    import threading, time, urllib.request
    import uvicorn
    PORT = 8172

    def _get(path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path))
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()

    t = threading.Thread(target=lambda: uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning"),
                         daemon=True)
    t.start()
    for _ in range(50):
        try:
            _get("/")
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise AssertionError("test server did not start")
    st, hd, body = _get("/static/app.js?v=%s" % __version__)
    cc = (hd.get("Cache-Control") or hd.get("cache-control") or "")
    check(st == 200 and "immutable" in cc and "max-age=31536000" in cc,
          "app.js?v=%s is long-cached and immutable: %s" % (__version__, cc))
    st, hd, _ = _get("/static/app.js?v=1.6")
    cc = (hd.get("Cache-Control") or hd.get("cache-control") or "")
    check(st == 200 and "no-store" in cc,
          "app.js?v=1.6 (stale URL) is no-store so the phone revalidates and gets this release")
    st, hd, body = _get("/sw.js")
    cc = (hd.get("Cache-Control") or hd.get("cache-control") or "")
    txt = body.decode()
    check(st == 200 and "no-store" in cc
          and ("const V='%s'" % __version__ in txt or 'const V="%s"' % __version__ in txt),
          "GET /sw.js returns the worker, no-store")
    st, hd, body = _get("/")
    cc = (hd.get("Cache-Control") or hd.get("cache-control") or "")
    check(st == 200 and "no-store" in cc and ("app.js?v=%s" % __version__) in body.decode(),
          "GET / is no-store and points at this version's JS")


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
